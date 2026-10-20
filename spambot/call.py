"""One phone call: screen the caller, then waste a spammer's time or take a real caller's message.

Transport-agnostic: the Twilio relay (relay.py) and the terminal chat (chat.py) both drive this.
"""
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from . import personas
from .llm import LLM, RefusalError, Verdict

log = logging.getLogger(__name__)

MAX_UNSURE_TURNS = 2  # still unsure after this many caller turns -> treat as a real caller


@dataclass
class Speak:
    text: str


@dataclass
class Digits:
    digits: str


@dataclass
class Hangup:
    pass


Event = Speak | Digits | Hangup


class MarkerFilter:
    """Pulls <press>N</press> and <end/> out of streamed text, even when split across chunks."""

    _PRESS = re.compile(r"<press>\s*([0-9*#]{1,6})\s*</press>")
    # Loose shape of an unfinished <press>…</press>; only used to delay speaking a few characters.
    _PRESS_PREFIX = re.compile(r"<p?r?e?s?s?>?[0-9*#\s]*<?/?p?r?e?s?s?>?")

    def __init__(self):
        self.buf = ""

    def feed(self, chunk: str) -> list[Event]:
        self.buf += chunk
        return self._drain(final=False)

    def flush(self) -> list[Event]:
        return self._drain(final=True)

    def _drain(self, final: bool) -> list[Event]:
        out: list[Event] = []
        while True:
            m = self._PRESS.search(self.buf)
            e = self.buf.find(personas.END)
            hits = [(m.start(), "press", m) if m else None, (e, "end", None) if e >= 0 else None]
            hits = [h for h in hits if h]
            if not hits:
                break
            pos, kind, match = min(hits, key=lambda h: h[0])
            if pos:
                out.append(Speak(self.buf[:pos]))
            if kind == "press":
                out.append(Digits(match.group(1)))
                self.buf = self.buf[match.end():]
            else:
                out.append(Hangup())
                self.buf = self.buf[pos + len(personas.END):]
        if final:
            text, self.buf = self.buf, ""
            if text:
                out.append(Speak(text))
        else:
            # Hold back anything that might be the start of a marker.
            cut = next((i for i, ch in enumerate(self.buf) if ch == "<" and self._maybe_marker(self.buf[i:])),
                       len(self.buf))
            if cut:
                out.append(Speak(self.buf[:cut]))
                self.buf = self.buf[cut:]
        return [ev for ev in out if not (isinstance(ev, Speak) and not ev.text)]

    def _maybe_marker(self, tail: str) -> bool:
        return len(tail) < 24 and (personas.END.startswith(tail) or bool(self._PRESS_PREFIX.fullmatch(tail)))


@dataclass
class Call:
    llm: LLM
    owner_name: str
    persona: personas.Persona
    caller: str = ""
    allowlisted: bool = False
    mode: str = "screening"           # screening -> spam | legit
    started: float = field(default_factory=time.time)
    history: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    unsure_turns: int = 0
    verdict_reason: str = ""

    def system_prompt(self) -> str:
        if self.mode == "spam":
            return self.persona.system_prompt()
        if self.mode == "legit":
            return personas.message_taker_prompt(self.owner_name)
        return personas.screener_prompt(self.owner_name)

    def _log(self, role: str, text: str) -> None:
        self.transcript.append({"t": round(time.time() - self.started, 1), "role": role, "text": text})

    def greeting_spoken(self, text: str) -> None:
        """Record the opening line Twilio spoke before the caller's first words."""
        self.history.append({"role": "user", "content": "(The phone rings and you pick up.)"})
        self.history.append({"role": "assistant", "content": text})
        self._log("bot", text)

    async def _screen(self) -> None:
        if self.allowlisted:
            self.mode, self.verdict_reason = "legit", "caller is on the allowlist"
            return
        caller_lines = "\n".join(f"Caller: {t['text']}" for t in self.transcript if t["role"] == "caller")
        try:
            v = await self.llm.classify(caller_lines)
        except Exception:
            log.exception("screening failed; still screening")
            v = Verdict(verdict="unsure", reason="screening call failed")
        self.verdict_reason = v.reason
        if v.verdict == "unsure":
            self.unsure_turns += 1
            if self.unsure_turns >= MAX_UNSURE_TURNS:
                self.mode, self.verdict_reason = "legit", "still unclear after screening; taking a message"
        else:
            self.mode = v.verdict

    async def respond(self, caller_text: str) -> AsyncIterator[Event]:
        """Handle what the caller just said and yield what to do, as it streams."""
        self._log("caller", caller_text)
        self.history.append({"role": "user", "content": caller_text})
        if self.mode == "screening":
            await self._screen()

        spoken, filt = [], MarkerFilter()
        try:
            try:
                async for chunk in self.llm.stream_reply(self.system_prompt(), self.history):
                    for ev in filt.feed(chunk):
                        if isinstance(ev, Speak):
                            spoken.append(ev.text)
                        elif isinstance(ev, Hangup) and self.mode == "spam":
                            continue  # time-wasters never hang up
                        yield ev
                for ev in filt.flush():
                    if isinstance(ev, Speak):
                        spoken.append(ev.text)
                    elif isinstance(ev, Hangup) and self.mode == "spam":
                        continue
                    yield ev
            except RefusalError:
                if not spoken:
                    line = "Sorry, you broke up there. What was that?"
                    spoken.append(line)
                    yield Speak(line)
        finally:
            # Runs on completion and when the caller talks over us (the task is cancelled).
            text = "".join(spoken).strip()
            if text:
                self.history.append({"role": "assistant", "content": text})
                self._log("bot", text)

    def interrupted(self, heard: str) -> None:
        """The caller talked over the last reply; keep only what they actually heard."""
        if self.history and self.history[-1]["role"] == "assistant":
            heard = heard.strip()
            if heard:
                self.history[-1]["content"] = heard + " —"
            else:
                self.history.pop()
            for t in reversed(self.transcript):
                if t["role"] == "bot":
                    t["text"] = (heard + " —") if heard else "(cut off)"
                    break

    def wrap_up_line(self) -> str:
        if self.mode == "spam":
            return "Oh, hold on, somebody's at the door. Stay right there, I'll be back in a jiffy."
        return "Sorry, I have to go now. Goodbye."

    @property
    def seconds(self) -> float:
        return time.time() - self.started

    def transcript_text(self) -> str:
        return "\n".join(f"{'Caller' if t['role'] == 'caller' else 'Assistant'}: {t['text']}" for t in self.transcript)
