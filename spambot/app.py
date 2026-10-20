"""Web server: Twilio voice webhook + ConversationRelay websocket.

  POST /voice         Twilio calls this when a call comes in; returns TwiML that connects the relay.
  WS   /relay         ConversationRelay websocket for one call.
  POST /connect-done  Twilio calls this when the relay ends; hangs up.
  GET  /calls         Recent calls and transcripts (needs ADMIN_TOKEN).
  GET  /health
"""
import asyncio
import json
import logging
import secrets
from xml.sax.saxutils import escape, quoteattr

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, Response

from . import config, personas, store
from .call import Call
from .llm import LLM, ClaudeLLM
from .relay import Session

log = logging.getLogger(__name__)

GREETING = "Hello?"
OVER_BUDGET = "Sorry, nobody can take your call right now. Please try again later."


def twiml(body: str) -> Response:
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    media_type="application/xml")


def create_app(settings: config.Settings | None = None, llm: LLM | None = None, conn=None,
               sms=None) -> FastAPI:
    s = settings or config.load()
    persona = personas.PERSONAS.get(s.persona) or personas.PERSONAS["earl"]
    app = FastAPI(title="spambot")
    state = {"llm": llm, "conn": conn or store.connect(s.db_path), "sms": sms}
    pending: dict[str, tuple[str, str]] = {}  # one-time relay token -> (call_sid, caller)

    def get_llm() -> LLM:
        if state["llm"] is None:
            state["llm"] = ClaudeLLM(s.model, s.effort)
        return state["llm"]

    def get_sms():
        if state["sms"] is None and s.twilio_account_sid and s.twilio_auth_token:
            from twilio.rest import Client
            client = Client(s.twilio_account_sid, s.twilio_auth_token)
            state["sms"] = lambda to, body: client.messages.create(to=to, from_=s.twilio_number, body=body)
        return state["sms"]

    async def verify_twilio(request: Request) -> dict:
        form = dict(await request.form())
        if s.allow_unsigned:
            return form
        if not s.twilio_auth_token or not s.public_url:
            raise HTTPException(500, "Set TWILIO_AUTH_TOKEN and PUBLIC_URL (or ALLOW_UNSIGNED=1 for local testing).")
        from twilio.request_validator import RequestValidator
        url = s.public_url + request.url.path
        if not RequestValidator(s.twilio_auth_token).validate(url, form, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "Bad Twilio signature")
        return form

    def ws_base(request: Request) -> str:
        base = s.public_url or str(request.base_url).rstrip("/")
        return base.replace("https://", "wss://").replace("http://", "ws://")

    @app.get("/health")
    async def health():
        return {"ok": True, "persona": persona.key, "model": s.model}

    @app.post("/voice")
    async def voice(request: Request):
        form = await verify_twilio(request)
        call_sid, caller = form.get("CallSid", ""), form.get("From", "")
        if store.minutes_today(state["conn"]) >= s.daily_minutes_cap:
            log.warning("daily minutes cap reached; declining %s", call_sid)
            return twiml(f"<Say>{escape(OVER_BUDGET)}</Say><Hangup/>")
        token = secrets.token_urlsafe(24)
        pending[token] = (call_sid, caller)
        attrs = {
            "url": f"{ws_base(request)}/relay?token={token}",
            "welcomeGreeting": GREETING,
            "interruptible": "any",
        }
        if s.tts_provider:
            attrs["ttsProvider"] = s.tts_provider
        if s.tts_voice:
            attrs["voice"] = s.tts_voice
        relay = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
        action = quoteattr((s.public_url or str(request.base_url).rstrip("/")) + "/connect-done")
        return twiml(f"<Connect action={action}><ConversationRelay {relay}/></Connect>")

    @app.post("/connect-done")
    async def connect_done(request: Request):
        await verify_twilio(request)
        return twiml("<Hangup/>")

    @app.websocket("/relay")
    async def relay(ws: WebSocket):
        entry = pending.pop(ws.query_params.get("token", ""), None)
        if entry is None:
            await ws.close(code=1008)
            return
        call_sid, caller = entry
        await ws.accept()
        setup = json.loads(await ws.receive_text())
        if setup.get("type") != "setup":
            log.warning("expected setup, got %s", setup.get("type"))
        caller = caller or setup.get("from", "")
        call = Call(llm=get_llm(), owner_name=s.owner_name, persona=persona, caller=caller,
                    allowlisted=caller in s.allowlist)
        call.greeting_spoken(GREETING)
        try:
            await Session(ws, call, call_sid, s.max_call_minutes * 60).run()
        finally:
            await finish_call(call_sid, call)

    async def finish_call(call_sid: str, call: Call) -> None:
        message = None
        heard_caller = any(t["role"] == "caller" for t in call.transcript)
        if call.mode == "legit" and heard_caller:
            try:
                message = await get_llm().summarize_message(call.transcript_text())
            except Exception:
                log.exception("summary failed")
                message = "Someone left a message; see the call log."
            send = get_sms()
            if send and s.owner_mobile:
                body = f"Call from {call.caller or 'unknown'}: {message}"
                try:
                    await asyncio.to_thread(send, s.owner_mobile, body[:1500])
                except Exception:
                    log.exception("SMS to owner failed")
        store.save_call(state["conn"], call_sid=call_sid, caller=call.caller, started=call.started,
                        seconds=call.seconds, mode=call.mode, persona=persona.key, reason=call.verdict_reason,
                        message=message, transcript=call.transcript if s.save_transcripts else None)
        log.info("call %s ended: %s, %.0fs", call_sid, call.mode, call.seconds)

    @app.get("/calls")
    async def calls(authorization: str = Header(default="")):
        if not s.admin_token or not secrets.compare_digest(authorization, f"Bearer {s.admin_token}"):
            raise HTTPException(401)
        return JSONResponse(store.recent_calls(state["conn"]))

    return app
