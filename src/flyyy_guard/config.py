"""Settings for flyyy-guard, read from arguments first and environment variables second."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_TIMEOUT_SECONDS = 3.0
CHECK_PATH = "/api/v1/guardrails/check"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class GuardSettings:
    url: str
    api_key: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    fail_open: bool = False

    @property
    def check_url(self) -> str:
        return self.url.rstrip("/") + CHECK_PATH

    def __repr__(self) -> str:  # never print the key
        return f"GuardSettings(url={self.url!r}, timeout={self.timeout}, fail_open={self.fail_open})"


def load_settings(
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: Optional[float] = None,
    fail_open: Optional[bool] = None,
) -> GuardSettings:
    """Build settings, falling back to FLYYY_URL / FLYYY_GUARDRAIL_KEY / FLYYY_GUARD_* env vars."""
    resolved_url = (url or os.getenv("FLYYY_URL") or "").strip()
    resolved_key = (api_key or os.getenv("FLYYY_GUARDRAIL_KEY") or "").strip()
    if not resolved_url:
        raise ValueError("flyyy-guard: FLYYY_URL is not set (pass url=... or set the FLYYY_URL env var).")
    if not resolved_key:
        raise ValueError(
            "flyyy-guard: FLYYY_GUARDRAIL_KEY is not set (create a guardrail key in FLYYY → "
            "GenAI Governance → your project → Guardrails)."
        )
    return GuardSettings(
        url=resolved_url,
        api_key=resolved_key,
        timeout=timeout if timeout is not None else _env_float("FLYYY_GUARD_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
        fail_open=fail_open if fail_open is not None else _env_bool("FLYYY_GUARD_FAIL_OPEN", False),
    )
