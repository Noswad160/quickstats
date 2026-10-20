"""Twilio ConversationRelay websocket: Twilio does speech-to-text and text-to-speech, we send text.

Protocol (Twilio -> us): setup, prompt {voicePrompt, last}, interrupt {utteranceUntilInterrupt}, dtmf, error.
(us -> Twilio): text {token, last}, sendDigits {digits}, end {handoffData}.
"""
import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from .call import Call, Digits, Hangup, Speak

log = logging.getLogger(__name__)


class Session:
    def __init__(self, ws: WebSocket, call: Call, call_sid: str, max_seconds: float):
        self.ws, self.call, self.call_sid, self.max_seconds = ws, call, call_sid, max_seconds
        self.reply_task: asyncio.Task | None = None
        self.ended = False

    async def send(self, msg: dict) -> None:
        if not self.ended:
            await self.ws.send_text(json.dumps(msg))

    async def end(self, reason: str) -> None:
        if not self.ended:
            await self.send({"type": "end", "handoffData": json.dumps({"reason": reason})})
            self.ended = True

    async def _reply(self, text: str) -> None:
        hang_up = False
        try:
            async for ev in self.call.respond(text):
                if isinstance(ev, Speak):
                    await self.send({"type": "text", "token": ev.text, "last": False})
                elif isinstance(ev, Digits):
                    await self.send({"type": "sendDigits", "digits": ev.digits})
                elif isinstance(ev, Hangup):
                    hang_up = True
            await self.send({"type": "text", "token": "", "last": True})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reply failed on %s", self.call_sid)
            await self.send({"type": "text", "token": "Sorry, say that again?", "last": True})
        if hang_up:
            await asyncio.sleep(4)  # let the goodbye finish playing
            await self.end("goodbye")

    async def _cancel_reply(self) -> None:
        """Stop the reply in progress and wait for it, so its partial text is in the history."""
        task, self.reply_task = self.reply_task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _watchdog(self) -> None:
        await asyncio.sleep(self.max_seconds)
        await self._cancel_reply()
        await self.send({"type": "text", "token": self.call.wrap_up_line(), "last": True})
        await asyncio.sleep(6)
        await self.end("time limit")

    async def run(self) -> None:
        watchdog = asyncio.create_task(self._watchdog())
        try:
            while True:
                msg = json.loads(await self.ws.receive_text())
                kind = msg.get("type")
                if kind == "prompt":
                    if not msg.get("last", True):
                        continue  # partial transcript; wait for the final one
                    text = (msg.get("voicePrompt") or "").strip()
                    if not text:
                        continue
                    await self._cancel_reply()
                    self.reply_task = asyncio.create_task(self._reply(text))
                elif kind == "interrupt":
                    await self._cancel_reply()
                    self.call.interrupted(msg.get("utteranceUntilInterrupt", ""))
                elif kind == "dtmf":
                    log.info("caller pressed %s", msg.get("digit"))
                elif kind == "error":
                    log.warning("relay error on %s: %s", self.call_sid, msg.get("description"))
        except WebSocketDisconnect:
            pass
        finally:
            watchdog.cancel()
            await self._cancel_reply()
