"""Settings, all from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _numbers(name: str) -> frozenset[str]:
    return frozenset(n.strip() for n in os.environ.get(name, "").split(",") if n.strip())


@dataclass(frozen=True)
class Settings:
    # Claude
    model: str = field(default_factory=lambda: os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: os.environ.get("CLAUDE_EFFORT", "low"))

    # Twilio
    twilio_account_sid: str = field(default_factory=lambda: os.environ.get("TWILIO_ACCOUNT_SID", ""))
    twilio_auth_token: str = field(default_factory=lambda: os.environ.get("TWILIO_AUTH_TOKEN", ""))
    twilio_number: str = field(default_factory=lambda: os.environ.get("TWILIO_NUMBER", ""))
    # Public https base URL Twilio reaches this server at, e.g. https://spambot.fly.dev
    public_url: str = field(default_factory=lambda: os.environ.get("PUBLIC_URL", "").rstrip("/"))
    # Local development only: accept webhooks without a Twilio signature.
    allow_unsigned: bool = field(default_factory=lambda: _bool("ALLOW_UNSIGNED", False))
    tts_provider: str = field(default_factory=lambda: os.environ.get("TTS_PROVIDER", ""))
    tts_voice: str = field(default_factory=lambda: os.environ.get("TTS_VOICE", ""))

    # You
    owner_name: str = field(default_factory=lambda: os.environ.get("OWNER_NAME", "the person you called"))
    owner_mobile: str = field(default_factory=lambda: os.environ.get("OWNER_MOBILE", ""))
    # Numbers that always get the polite message-taker, never a time-waster.
    allowlist: frozenset[str] = field(default_factory=lambda: _numbers("ALLOWLIST"))

    # Limits: every minute on a call costs money (phone, speech and Claude).
    max_call_minutes: float = field(default_factory=lambda: float(os.environ.get("MAX_CALL_MINUTES", "30")))
    daily_minutes_cap: float = field(default_factory=lambda: float(os.environ.get("DAILY_MINUTES_CAP", "180")))

    persona: str = field(default_factory=lambda: os.environ.get("PERSONA", "earl"))
    save_transcripts: bool = field(default_factory=lambda: _bool("SAVE_TRANSCRIPTS", True))
    db_path: str = field(default_factory=lambda: os.environ.get("DB_PATH", "data/spambot.sqlite"))
    # Bearer token for GET /calls; unset disables the endpoint.
    admin_token: str = field(default_factory=lambda: os.environ.get("ADMIN_TOKEN", ""))


def load() -> Settings:
    return Settings()
