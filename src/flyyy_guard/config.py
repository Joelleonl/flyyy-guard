"""Settings for flyyy-guard, read from arguments first and environment variables second."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_TIMEOUT_SECONDS = 10.0
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
    # A FLYYY guardrail key (fg_...). When empty, the project's Langfuse keys are sent instead.
    api_key: str = ""
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    fail_open: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    @property
    def check_url(self) -> str:
        return self.url.rstrip("/") + CHECK_PATH

    @property
    def authorization(self) -> str:
        if self.api_key:
            return f"Bearer {self.api_key}"
        pair = f"{self.langfuse_public_key}:{self.langfuse_secret_key}".encode("utf-8")
        return "Basic " + base64.b64encode(pair).decode("ascii")

    def __repr__(self) -> str:  # never print the key
        return f"GuardSettings(url={self.url!r}, timeout={self.timeout}, fail_open={self.fail_open})"


def load_settings(
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: Optional[float] = None,
    fail_open: Optional[bool] = None,
) -> GuardSettings:
    """Build settings from arguments, falling back to environment variables.

    Credentials: FLYYY_GUARDRAIL_KEY if set, otherwise the LANGFUSE_PUBLIC_KEY /
    LANGFUSE_SECRET_KEY the agent already uses for tracing.
    """
    resolved_url = (url or os.getenv("FLYYY_URL") or "").strip()
    resolved_key = (api_key or os.getenv("FLYYY_GUARDRAIL_KEY") or "").strip()
    public_key = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
    if not resolved_url:
        raise ValueError("flyyy-guard: FLYYY_URL is not set (pass url=... or set the FLYYY_URL env var).")
    if not resolved_key and not (public_key and secret_key):
        raise ValueError(
            "flyyy-guard: no credentials. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
            "(your project's keys from FLYYY → GenAI Governance), or FLYYY_GUARDRAIL_KEY."
        )
    return GuardSettings(
        url=resolved_url,
        api_key=resolved_key,
        langfuse_public_key="" if resolved_key else public_key,
        langfuse_secret_key="" if resolved_key else secret_key,
        timeout=timeout if timeout is not None else _env_float("FLYYY_GUARD_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
        fail_open=fail_open if fail_open is not None else _env_bool("FLYYY_GUARD_FAIL_OPEN", False),
    )
