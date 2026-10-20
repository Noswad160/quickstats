import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from spambot import config, personas, store
from spambot.app import create_app
from spambot.call import Call, Digits, Hangup, MarkerFilter, Speak
from spambot.llm import RefusalError, Verdict


class FakeLLM:
    """Scripted stand-in for Claude: verdicts and replies come from lists."""

    def __init__(self, verdicts=("spam",), replies=("Well hello there!",), chunk=4, delay=0.0):
        self.verdicts, self.replies = list(verdicts), list(replies)
        self.chunk, self.delay = chunk, delay
        self.systems, self.classified = [], []

    async def stream_reply(self, system, messages):
        self.systems.append(system)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if reply is RefusalError:
            raise RefusalError()
        for i in range(0, len(reply), self.chunk):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield reply[i:i + self.chunk]

    async def classify(self, transcript):
        self.classified.append(transcript)
        v = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        return Verdict(verdict=v, reason=f"fake {v}")

    async def summarize_message(self, transcript):
        return "Dr. Lee's office called about Tuesday's appointment."


def make_call(llm, **kw):
    c = Call(llm=llm, owner_name="Dawson", persona=personas.PERSONAS["earl"], **kw)
    c.greeting_spoken("Hello?")
    return c


async def collect(agen):
    return [ev async for ev in agen]


def spoken(events):
    return "".join(e.text for e in events if isinstance(e, Speak))


# --- markers -------------------------------------------------------------------

def test_marker_filter_handles_split_markers():
    f, out = MarkerFilter(), []
    for chunk in ["Hold on, ", "I'll press it <pr", "ess>1</pr", "ess> now. Bye<en", "d/>", " a < b"]:
        out += f.feed(chunk)
    out += f.flush()
    assert [type(e).__name__ for e in out if not isinstance(e, Speak)] == ["Digits", "Hangup"]
    assert next(e for e in out if isinstance(e, Digits)).digits == "1"
    assert spoken(out) == "Hold on, I'll press it  now. Bye a < b"


# --- screening and modes -----------------------------------------------------------

def test_spam_caller_gets_persona_and_never_hangs_up():
    llm = FakeLLM(verdicts=["spam"], replies=["Oh my, a warranty? Tell me more. <end/>"])
    call = make_call(llm)
    events = asyncio.run(collect(call.respond("This is about your car's extended warranty.")))
    assert call.mode == "spam"
    assert "Earl" in llm.systems[-1]
    assert not any(isinstance(e, Hangup) for e in events)          # time-wasters don't hang up
    assert spoken(events).strip() == "Oh my, a warranty? Tell me more."
    assert call.history[-1] == {"role": "assistant", "content": "Oh my, a warranty? Tell me more."}


def test_legit_caller_gets_message_taker_and_can_hang_up():
    llm = FakeLLM(verdicts=["legit"], replies=["Got it, I'll pass that on. Goodbye. <end/>"])
    call = make_call(llm)
    events = asyncio.run(collect(call.respond("Hi, this is Dr. Lee's office for Dawson.")))
    assert call.mode == "legit"
    assert "automated call assistant" in llm.systems[-1]
    assert any(isinstance(e, Hangup) for e in events)


def test_unsure_twice_falls_back_to_taking_a_message():
    llm = FakeLLM(verdicts=["unsure"], replies=["Sorry, who's this?"])
    call = make_call(llm)
    asyncio.run(collect(call.respond("Hello?")))
    assert call.mode == "screening"
    asyncio.run(collect(call.respond("Hello, hello?")))
    assert call.mode == "legit"


def test_allowlisted_caller_skips_classifier():
    llm = FakeLLM(verdicts=["spam"])
    call = make_call(llm, allowlisted=True)
    asyncio.run(collect(call.respond("It's Mom.")))
    assert call.mode == "legit" and llm.classified == []


def test_screening_stops_after_verdict():
    llm = FakeLLM(verdicts=["spam"])
    call = make_call(llm)
    asyncio.run(collect(call.respond("Final notice!")))
    asyncio.run(collect(call.respond("Are you there?")))
    assert len(llm.classified) == 1


def test_refusal_says_something_harmless():
    call = make_call(FakeLLM(verdicts=["spam"], replies=[RefusalError]))
    events = asyncio.run(collect(call.respond("Give me your bank login.")))
    assert "say that again" in spoken(events) or "What was that" in spoken(events)


def test_interrupt_keeps_only_what_was_heard():
    call = make_call(FakeLLM(verdicts=["spam"], replies=["Well now, let me tell you about Dottie's pie."]))
    asyncio.run(collect(call.respond("Hello sir")))
    call.interrupted("Well now, let me")
    assert call.history[-1]["content"] == "Well now, let me —"
    assert call.transcript[-1]["text"] == "Well now, let me —"


# --- web server ----------------------------------------------------------------------

def settings(**kw):
    base = dict(allow_unsigned=True, db_path=":memory:", owner_mobile="+15015550100", owner_name="Dawson",
                max_call_minutes=30, daily_minutes_cap=180, admin_token="secret")
    base.update(kw)
    return config.Settings(**base)


def relay_url(twiml: str) -> str:
    start = twiml.index('url="') + 5
    return twiml[start:twiml.index('"', start)].replace("&amp;", "&")


def test_voice_webhook_returns_conversation_relay():
    client = TestClient(create_app(settings(), llm=FakeLLM(), conn=store.connect(":memory:")))
    r = client.post("/voice", data={"CallSid": "CA1", "From": "+15005550006"})
    assert r.status_code == 200
    assert "<ConversationRelay" in r.text and 'welcomeGreeting="Hello?"' in r.text
    assert "/relay?token=" in relay_url(r.text)


def test_unsigned_webhook_is_rejected_in_production():
    s = settings(allow_unsigned=False, twilio_auth_token="tok", public_url="https://bot.example.com")
    client = TestClient(create_app(s, llm=FakeLLM(), conn=store.connect(":memory:")))
    assert client.post("/voice", data={"CallSid": "CA1"}).status_code == 403


def test_daily_cap_declines_calls():
    conn = store.connect(":memory:")
    import time
    store.save_call(conn, call_sid="old", caller="x", started=time.time(), seconds=181 * 60, mode="spam",
                    persona="earl", reason="", message=None, transcript=None)
    client = TestClient(create_app(settings(), llm=FakeLLM(), conn=conn))
    r = client.post("/voice", data={"CallSid": "CA2"})
    assert "<Hangup/>" in r.text and "ConversationRelay" not in r.text


def test_relay_rejects_unknown_token():
    client = TestClient(create_app(settings(), llm=FakeLLM(), conn=store.connect(":memory:")))
    with pytest.raises(Exception):
        with client.websocket_connect("/relay?token=nope") as ws:
            ws.receive_text()


def run_call(llm, caller_lines, sms_log, caller="+15005550006"):
    conn = store.connect(":memory:")
    app = create_app(settings(), llm=llm, conn=conn, sms=lambda to, body: sms_log.append((to, body)))
    client = TestClient(app)
    url = relay_url(client.post("/voice", data={"CallSid": "CA9", "From": caller}).text)
    path = url[url.index("/relay"):]
    received = []
    with client.websocket_connect(path) as ws:
        ws.send_text(json.dumps({"type": "setup", "callSid": "CA9", "from": caller}))
        for line in caller_lines:
            ws.send_text(json.dumps({"type": "prompt", "voicePrompt": line, "last": True}))
            while True:
                msg = json.loads(ws.receive_text())
                received.append(msg)
                if msg["type"] == "end" or (msg["type"] == "text" and msg["last"]):
                    break
    return conn, received


def test_full_spam_call_over_websocket():
    sms = []
    llm = FakeLLM(verdicts=["spam"], replies=["Well hello! Hang on, I'll press <press>1</press> for you."])
    conn, received = run_call(llm, ["Press 1 to speak to an agent about your debt."], sms)
    kinds = [m["type"] for m in received]
    assert "sendDigits" in kinds and {"type": "sendDigits", "digits": "1"} in received
    assert received[-1] == {"type": "text", "token": "", "last": True}
    row = store.recent_calls(conn)[0]
    assert row["mode"] == "spam" and row["persona"] == "earl" and sms == []
    assert [t["role"] for t in row["transcript"]] == ["bot", "caller", "bot"]


def test_full_legit_call_texts_the_owner():
    sms = []
    llm = FakeLLM(verdicts=["legit"], replies=["Thanks, I'll let Dawson know. Goodbye. <end/>"])
    conn, received = run_call(llm, ["Hi, it's Dr. Lee's office, call us back about Tuesday."], sms)
    assert sms and sms[0][0] == "+15015550100" and "Dr. Lee" in sms[0][1]
    assert store.recent_calls(conn)[0]["message"].startswith("Dr. Lee")


def test_calls_endpoint_needs_token():
    client = TestClient(create_app(settings(), llm=FakeLLM(), conn=store.connect(":memory:")))
    assert client.get("/calls").status_code == 401
    assert client.get("/calls", headers={"Authorization": "Bearer secret"}).json() == []


def test_interrupt_mid_reply_over_websocket():
    llm = FakeLLM(verdicts=["spam"], replies=["Well now, " + "let me tell you about the ice storm. " * 20,
                                             "Oh, sorry dear, go ahead."], chunk=8, delay=0.01)
    conn = store.connect(":memory:")
    client = TestClient(create_app(settings(), llm=llm, conn=conn))
    url = relay_url(client.post("/voice", data={"CallSid": "CA5", "From": "+15005550006"}).text)
    with client.websocket_connect(url[url.index("/relay"):]) as ws:
        ws.send_text(json.dumps({"type": "setup", "callSid": "CA5"}))
        ws.send_text(json.dumps({"type": "prompt", "voicePrompt": "Your account is suspended.", "last": True}))
        assert json.loads(ws.receive_text())["type"] == "text"          # reply has started streaming
        ws.send_text(json.dumps({"type": "interrupt", "utteranceUntilInterrupt": "Well now,"}))
        ws.send_text(json.dumps({"type": "prompt", "voicePrompt": "Sir, listen to me.", "last": True}))
        while True:  # the cancelled first reply never sends last=True, so this is the second reply's end
            msg = json.loads(ws.receive_text())
            if msg["type"] == "text" and msg["last"]:
                break
    t = store.recent_calls(conn)[0]["transcript"]
    assert [x["text"] for x in t if x["role"] == "bot"][1] == "Well now, —"
    assert [x["text"] for x in t if x["role"] == "caller"] == ["Your account is suspended.", "Sir, listen to me."]


def test_screening_error_keeps_screening():
    class Broken(FakeLLM):
        async def classify(self, transcript):
            raise RuntimeError("network down")
    call = make_call(Broken(replies=["Sorry, who's calling?"]))
    events = asyncio.run(collect(call.respond("Hi there")))
    assert call.mode == "screening" and spoken(events) == "Sorry, who's calling?"
