from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SUPPORTED_AI_PROVIDERS = {"openrouter", "openai", "rule_based"}
LOCAL_ENV_FILES = (".env.local", ".env")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_ACCOUNT_KEY = "personal"
DEFAULT_AI_MAX_OUTPUT_TOKENS = 700


def load_local_env(base_dir: str | os.PathLike[str] | None = None) -> None:
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    for filename in LOCAL_ENV_FILES:
        path = root / filename
        if path.exists():
            _load_env_file(path)


def _load_env_file(path: Path) -> None:
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        name, value = parsed
        if not ENV_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid environment variable name in {path}:{line_number}: {name}")
        os.environ.setdefault(name, value)


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").lstrip()
    if "=" not in stripped:
        return None

    name, raw_value = stripped.split("=", 1)
    name = name.strip()
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    else:
        value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
    return name, value


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _scopes() -> tuple[str, ...]:
    value = os.getenv("GOOGLE_OAUTH_SCOPES")
    if not value:
        return DEFAULT_SCOPES
    scopes = tuple(part.strip() for part in value.replace(",", " ").split() if part.strip())
    if GMAIL_SEND_SCOPE not in scopes:
        return (*scopes, GMAIL_SEND_SCOPE)
    return scopes


def _ai_provider() -> str:
    return os.getenv("AI_PROVIDER", "openrouter").strip().lower().replace("-", "_")


@dataclass(frozen=True)
class Settings:
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    google_scopes: tuple[str, ...]

    supabase_url: str
    supabase_service_role_key: str
    account_key: str

    openai_api_key: str
    openai_model: str
    ai_max_output_tokens: int

    gmail_from_email: str
    summary_recipient_email: str

    timezone_name: str
    strict_data_types: bool
    ai_provider: str = "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"

    @classmethod
    def from_env(cls) -> "Settings":
        load_local_env()
        return cls(
            google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            google_refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", ""),
            google_scopes=_scopes(),
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            account_key=DEFAULT_ACCOUNT_KEY,
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            ai_max_output_tokens=DEFAULT_AI_MAX_OUTPUT_TOKENS,
            ai_provider=_ai_provider(),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "openrouter/free"),
            gmail_from_email=os.getenv("GMAIL_FROM_EMAIL", ""),
            summary_recipient_email=os.getenv("SUMMARY_RECIPIENT_EMAIL", ""),
            timezone_name=os.getenv("HEALTHOS_TIMEZONE", "America/Chicago"),
            strict_data_types=_bool("HEALTHOS_STRICT_DATA_TYPES", False),
        )

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def email_from(self) -> str:
        return self.gmail_from_email

    @property
    def health_scopes(self) -> tuple[str, ...]:
        return tuple(scope for scope in self.google_scopes if scope != GMAIL_SEND_SCOPE)

    @property
    def gmail_scopes(self) -> tuple[str, ...]:
        return (GMAIL_SEND_SCOPE,)

    def validate_sync(self) -> None:
        missing = [
            name
            for name, value in (
                ("GOOGLE_CLIENT_ID", self.google_client_id),
                ("GOOGLE_CLIENT_SECRET", self.google_client_secret),
                ("GOOGLE_REFRESH_TOKEN", self.google_refresh_token),
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing required sync settings: {', '.join(missing)}")

    def validate_storage(self) -> None:
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing required storage settings: {', '.join(missing)}")

    def validate_ai(self) -> None:
        if self.ai_provider not in SUPPORTED_AI_PROVIDERS:
            supported = ", ".join(sorted(SUPPORTED_AI_PROVIDERS))
            raise ValueError(f"Unsupported AI_PROVIDER: {self.ai_provider}. Use one of: {supported}.")
        if self.ai_provider == "rule_based":
            return
        if self.ai_provider == "openrouter" and not self.openrouter_api_key:
            raise ValueError("Missing OPENROUTER_API_KEY. Use AI_PROVIDER=rule_based to avoid external AI.")
        if self.ai_provider == "openai" and not self.openai_api_key:
            raise ValueError("Missing OPENAI_API_KEY. Use AI_PROVIDER=rule_based to avoid external AI.")

    def validate_email(self) -> None:
        missing = [
            name
            for name, value in (
                ("GOOGLE_CLIENT_ID", self.google_client_id),
                ("GOOGLE_CLIENT_SECRET", self.google_client_secret),
                ("GOOGLE_REFRESH_TOKEN", self.google_refresh_token),
                ("GMAIL_FROM_EMAIL", self.email_from),
                ("SUMMARY_RECIPIENT_EMAIL", self.summary_recipient_email),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing required Gmail API email settings: {', '.join(missing)}")
        if GMAIL_SEND_SCOPE not in self.google_scopes:
            raise ValueError(f"GOOGLE_OAUTH_SCOPES must include {GMAIL_SEND_SCOPE}")
