"""Claude calls: streamed replies, call screening, and message summaries."""
from collections.abc import AsyncIterator
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel

Message = dict  # {"role": "user"|"assistant", "content": str}

# Models that support server-side refusal fallback with `fallbacks: "default"`.
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")


class Verdict(BaseModel):
    verdict: Literal["spam", "legit", "unsure"]
    reason: str


class LLM(Protocol):
    def stream_reply(self, system: str, messages: list[Message]) -> AsyncIterator[str]: ...
    async def classify(self, transcript: str) -> Verdict: ...
    async def summarize_message(self, transcript: str) -> str: ...


CLASSIFY_PROMPT = """\
You screen phone calls for one person. Below is the start of a call: what the caller said after it was \
answered. Decide:
- "spam": robocalls, telemarketing, scams, "extended warranty", "final notice", fake government, tech \
support, debt relief, prize/lottery, Medicare/insurance cold calls, recorded sales pitches, silence-then-pitch.
- "legit": a real person or business with a plausible reason to reach this specific person (doctor, school, \
delivery, employer, a named friend or relative, a callback they asked for, appointment reminders).
- "unsure": not enough to tell yet (just "hello?", silence, or a question back).
When in doubt between spam and legit, choose legit: wasting a real person's time is worse than missing a spammer.

Call so far:
{transcript}"""

SUMMARY_PROMPT = """\
Summarize this phone message for a text message to the person it was for: who called, their callback \
number if given, and what it's about. Two sentences at most, no preamble.

{transcript}"""


class ClaudeLLM:
    def __init__(self, model: str, effort: str = "low", client: anthropic.AsyncAnthropic | None = None):
        self.model, self.effort = model, effort
        self.client = client or anthropic.AsyncAnthropic()

    def _fallback_args(self) -> dict:
        if self.model in _FALLBACK_MODELS:
            return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        return {}

    async def stream_reply(self, system: str, messages: list[Message]) -> AsyncIterator[str]:
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=1024,  # a few spoken sentences; long monologues are cut by the prompt, not here
            system=system,
            messages=messages,
            output_config={"effort": self.effort},
            **self._fallback_args(),
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
        if final.stop_reason == "refusal":
            # Whatever streamed is discarded by the caller; say something harmless instead.
            raise RefusalError()

    async def classify(self, transcript: str) -> Verdict:
        resp = await self.client.beta.messages.parse(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": CLASSIFY_PROMPT.format(transcript=transcript)}],
            output_config={"effort": "low"},
            output_format=Verdict,
            **self._fallback_args(),
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            return Verdict(verdict="legit", reason="classifier gave no answer")
        return resp.parsed_output

    async def summarize_message(self, transcript: str) -> str:
        resp = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": SUMMARY_PROMPT.format(transcript=transcript)}],
            output_config={"effort": "low"},
            **self._fallback_args(),
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or "Someone left a message; see the transcript."


class RefusalError(Exception):
    pass
