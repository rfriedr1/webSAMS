"""Application configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def _load_local_env_files() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    for filename in (".env", ".env.local"):
        env_file = repo_root / filename
        if env_file.exists():
            load_dotenv(env_file, override=False)


_load_local_env_files()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_name_from_url(database_url: str) -> str:
    try:
        url = make_url(database_url)
    except ArgumentError:
        return "unknown"

    database = url.database or ""
    if database == "":
        return "unknown"
    if url.get_backend_name() == "sqlite":
        # SQLite URLs can expose file paths; surface just the filename in the UI.
        return Path(database).name or database
    return database


@dataclass(frozen=True)
class Settings:
    app_title: str
    database_url: str
    setup_data_file: Path
    debug: bool
    sql_echo: bool

    @property
    def database_name(self) -> str:
        return _database_name_from_url(self.database_url)

    @classmethod
    def from_env(cls) -> "Settings":
        default_setup_file = Path(__file__).resolve().parent / "setup_data.json"
        setup_file_env = os.getenv("SAMS_SETUP_DATA_FILE")
        if setup_file_env:
            setup_data_file = Path(setup_file_env).expanduser()
        else:
            setup_data_file = default_setup_file
        database_url = (os.getenv("SAMS_DATABASE_URL") or "").strip()
        if database_url == "":
            raise RuntimeError(
                "SAMS_DATABASE_URL is required. Set it in your environment or in a local .env file "
                "(see .env.example)."
            )
        return cls(
            app_title=os.getenv("SAMS_APP_TITLE", "SAMS Web"),
            database_url=database_url,
            setup_data_file=setup_data_file,
            debug=_env_flag("SAMS_DEBUG", default=False),
            sql_echo=_env_flag("SAMS_SQL_ECHO", default=False),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
