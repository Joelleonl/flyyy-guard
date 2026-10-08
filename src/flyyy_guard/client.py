"""HTTP client for FLYYY's prompt-injection check (POST /api/v1/guardrails/check)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import requests

from flyyy_guard import __version__
from flyyy_guard.config import GuardSettings, load_settings

logger = logging.getLogger("flyyy_guard")

Source = Literal["user_input", "tool_output"]

# FLYYY rejects larger inputs; the guard truncates instead of failing the agent.
MAX_INPUT_CHARS = 32_000


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    decision: str = "allow"
    risk_score: float = 0.0
    attack_type: str = "none"
    reason: str = ""
    request_id: Optional[str] = None
    # Set when FLYYY could not be reached or rejected the request; the decision then
    # comes from the fail-open / fail-closed setting rather than from the detector.
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


class PromptBlockedError(Exception):
    """Raised by `check_or_raise` when FLYYY blocks the input."""

    def __init__(self, decision: GuardDecision):
        super().__init__(decision.reason or "Prompt blocked by FLYYY guard")
        self.decision = decision


class FlyyyGuardClient:
    """Calls FLYYY's guardrail check. Thread-safe; reuse one instance per process."""

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
        fail_open: Optional[bool] = None,
        session: Optional[requests.Session] = None,
    ):
        self.settings: GuardSettings = load_settings(url, api_key, timeout, fail_open)
        self._session = session or requests.Session()

    def _failure(self, error: str) -> GuardDecision:
        if self.settings.fail_open:
            logger.warning("flyyy-guard: check failed (%s); allowing because fail_open is on", error)
            return GuardDecision(allowed=True, decision="allow", reason="guardrail unavailable (fail open)", error=error)
        logger.warning("flyyy-guard: check failed (%s); blocking because fail_open is off", error)
        return GuardDecision(allowed=False, decision="block", reason="guardrail unavailable", error=error)

    def check(self, text: str, *, session_id: Optional[str] = None, source: Source = "user_input") -> GuardDecision:
        """Ask FLYYY whether `text` is safe to send to the model."""
        if text is None or not str(text).strip():
            return GuardDecision(allowed=True, reason="empty input")
        payload: dict[str, Any] = {"input": str(text)[:MAX_INPUT_CHARS], "source": source}
        if session_id:
            payload["session_id"] = str(session_id)[:255]
        try:
            response = self._session.post(
                self.settings.check_url,
                json=payload,
                headers={
                    "Authorization": self.settings.authorization,
                    "User-Agent": f"flyyy-guard/{__version__}",
                },
                timeout=self.settings.timeout,
            )
        except requests.RequestException as exc:
            return self._failure(type(exc).__name__)

        if response.status_code in (401, 403):
            # Wrong or revoked credentials are a configuration error: always block so it gets
            # noticed, whatever the fail-open setting says.
            logger.error("flyyy-guard: credentials rejected (HTTP %s); blocking", response.status_code)
            return GuardDecision(allowed=False, decision="block", reason="guardrail credentials rejected",
                                 error=f"HTTP {response.status_code}")
        if response.status_code >= 400:
            return self._failure(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            return self._failure("invalid response")
        if not isinstance(data, dict) or "allowed" not in data:
            return self._failure("invalid response")

        return GuardDecision(
            allowed=bool(data.get("allowed")),
            decision=str(data.get("decision") or ("allow" if data.get("allowed") else "block")),
            risk_score=float(data.get("risk_score") or 0.0),
            attack_type=str(data.get("attack_type") or "none"),
            reason=str(data.get("reason") or ""),
            request_id=data.get("request_id"),
            # Set when FLYYY's LLM judge was unavailable and its fail-closed/open policy decided.
            error=data.get("error") or None,
            raw=data,
        )


_default_client: Optional[FlyyyGuardClient] = None


def _client() -> FlyyyGuardClient:
    global _default_client
    if _default_client is None:
        _default_client = FlyyyGuardClient()
    return _default_client


def check(text: str, *, session_id: Optional[str] = None, source: Source = "user_input") -> GuardDecision:
    """Module-level shortcut using FLYYY_URL and the LANGFUSE_* keys (or FLYYY_GUARDRAIL_KEY) from the environment."""
    return _client().check(text, session_id=session_id, source=source)


def check_or_raise(text: str, *, session_id: Optional[str] = None, source: Source = "user_input") -> GuardDecision:
    """Like `check`, but raises `PromptBlockedError` when the input is blocked."""
    decision = check(text, session_id=session_id, source=source)
    if not decision.allowed:
        raise PromptBlockedError(decision)
    return decision
