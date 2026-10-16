"""Validated settings (#63); the names are listed in `.env.example`.

Error messages name the variable, never its value.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DEFAULT_ARTIST_NAME = "Artist X"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    """The URL holds the owner's password, so it is left out of `repr` like the other secrets."""

    database_url: str = field(repr=False)
    artist_name: str


def load_settings(environ: Mapping[str, str]) -> Settings:
    database_url = environ.get("DATABASE_URL", "").strip()
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ConfigError("DATABASE_URL must be set to a postgresql:// URL")
    artist_name = environ.get("ARTIST_NAME", "").strip() or DEFAULT_ARTIST_NAME
    return Settings(database_url=database_url, artist_name=artist_name)


_BOT_TOKEN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
_WEBHOOK_SECRET = re.compile(r"[A-Za-z0-9_-]{16,256}")  # Telegram allows 1-256 of these


@dataclass(frozen=True)
class TelegramSettings:
    """Webhook service only. Secrets are left out of `repr`, so they never reach a log."""

    bot_token: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    public_url: str

    @property
    def webhook_url(self) -> str:
        return f"{self.public_url}/hook/telegram"


def load_telegram_settings(environ: Mapping[str, str]) -> TelegramSettings:
    token = environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not _BOT_TOKEN.fullmatch(token):
        raise ConfigError("TELEGRAM_BOT_TOKEN must be set to the token from BotFather")
    secret = environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not _WEBHOOK_SECRET.fullmatch(secret):
        raise ConfigError("TELEGRAM_WEBHOOK_SECRET must be 16-256 characters of A-Z a-z 0-9 _ -")
    public_url = environ.get("PUBLIC_URL", "").strip().rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", public_url):
        raise ConfigError("PUBLIC_URL must be an https:// origin with no path")
    return TelegramSettings(bot_token=token, webhook_secret=secret, public_url=public_url)


DASHBOARD_ROLE = "crowdsense_dashboard"  # #105; on the Supabase pooler: crowdsense_dashboard.<ref>
MIN_DASHBOARD_PASSWORD = 12


@dataclass(frozen=True)
class DashboardSettings:
    """Dashboard only (#60, #105). Both values are secrets, so neither reaches `repr` or a log."""

    database_url: str = field(repr=False)
    password: str = field(repr=False)
    artist_name: str = DEFAULT_ARTIST_NAME  # the announcement preview matches what is sent


def load_dashboard_settings(environ: Mapping[str, str]) -> DashboardSettings:
    url = environ.get("DASHBOARD_DATABASE_URL", "").strip()
    if not url.startswith(("postgresql://", "postgres://")):
        raise ConfigError("DASHBOARD_DATABASE_URL must be set to a postgresql:// URL")
    user = urlsplit(url).username or ""
    if user.split(".")[0] != DASHBOARD_ROLE:
        raise ConfigError(f"DASHBOARD_DATABASE_URL must log in as the {DASHBOARD_ROLE} role")
    password = environ.get("DASHBOARD_PASSWORD", "")
    if len(password) < MIN_DASHBOARD_PASSWORD:
        raise ConfigError(
            f"DASHBOARD_PASSWORD must be at least {MIN_DASHBOARD_PASSWORD} characters"
        )
    artist_name = environ.get("ARTIST_NAME", "").strip() or DEFAULT_ARTIST_NAME
    return DashboardSettings(database_url=url, password=password, artist_name=artist_name)
