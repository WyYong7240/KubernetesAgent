from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings kept deliberately small for the first control-plane slice."""

    environment: str = "development"
    database_url: str | None = None
    dagger_webhook_secret: str | None = None

    @property
    def requires_dagger_signature(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @classmethod
    def from_environment(cls, env_file: Path | None = None) -> "Settings":
        # Read the same file for both FastAPI and Alembic, independent of cwd.
        # Process environment always takes precedence, including explicit blanks.
        values = {**dotenv_values(env_file or PROJECT_ROOT / ".env"), **os.environ}
        return cls(
            environment=values.get("APP_ENV") or "development",
            database_url=values.get("DATABASE_URL") or None,
            dagger_webhook_secret=values.get("DAGGER_WEBHOOK_SECRET") or None,
        )
