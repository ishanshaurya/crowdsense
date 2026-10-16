"""Validated settings (#63); the names are listed in `.env.example`."""

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_ARTIST_NAME = "Artist X"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    artist_name: str


def load_settings(environ: Mapping[str, str]) -> Settings:
    database_url = environ.get("DATABASE_URL", "").strip()
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ConfigError("DATABASE_URL must be set to a postgresql:// URL")
    artist_name = environ.get("ARTIST_NAME", "").strip() or DEFAULT_ARTIST_NAME
    return Settings(database_url=database_url, artist_name=artist_name)
