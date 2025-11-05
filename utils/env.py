"""Environment variable helpers for the GovBeacon SAM.gov pipeline."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


_ENV_LOADED = False


def load_env_settings(env_path: Optional[Path] = None) -> None:
    """Ensure environment variables are loaded from a .env file.

    Args:
        env_path: Optional path to a .env file. Defaults to project root/.env.
    """

    global _ENV_LOADED

    if _ENV_LOADED:
        return

    if env_path is None:
        env_path = Path.cwd() / ".env"

    load_dotenv(dotenv_path=env_path, override=False)
    _ENV_LOADED = True


def require_env(name: str) -> str:
    """Return the requested environment variable or raise a helpful error."""

    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable '{name}'. Set it in the shell or the .env file."
        )
    return value

