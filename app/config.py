from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    firebase_service_account_file: str | None
    firebase_service_account_json: dict[str, Any] | None
    cors_origins: list[str]
    env: str


def _parse_cors(value: str | None) -> list[str]:
    if not value:
        return [
            "http://localhost:3000",
            "http://localhost:5173",
        ]
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def get_settings() -> Settings:
    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=backend_dir / ".env")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    # Accept common Postgres URL forms and normalize to SQLAlchemy+psycopg.
    # We install `psycopg` (v3), so `postgresql://` (which defaults to psycopg2) may fail.
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)

    firebase_service_account_file = os.getenv("FIREBASE_SERVICE_ACCOUNT_FILE")

    firebase_service_account_json: dict[str, Any] | None = None
    firebase_service_account_json_raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if firebase_service_account_json_raw:
        firebase_service_account_json = json.loads(firebase_service_account_json_raw)

    return Settings(
        database_url=database_url,
        firebase_service_account_file=firebase_service_account_file,
        firebase_service_account_json=firebase_service_account_json,
        cors_origins=_parse_cors(os.getenv("CORS_ORIGINS")),
        env=os.getenv("ENV", "dev"),
    )
