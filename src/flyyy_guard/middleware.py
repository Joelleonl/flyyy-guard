"""LangChain v1 agent middleware that checks the user's prompt with FLYYY before the agent runs.

Usage:
    from flyyy_guard import FlyyyGuardMiddleware
    agent = create_agent(model=..., tools=..., middleware=[FlyyyGuardMiddleware()])
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

try:
    from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
    from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
    raise ImportError(
        'FlyyyGuardMiddleware needs LangChain v1. Install it with: pip install "flyyy-guard[langchain]"'
    ) from exc

from flyyy_guard.client import FlyyyGuardClient, GuardDecision, Source

logger = logging.getLogger("flyyy_guard")

DEFAULT_BLOCK_MESSAGE = "Your request was blocked by policy."
# Used when the check itself failed (FLYYY unreachable, timeout), so an outage is not
# mistaken for a detected attack.
DEFAULT_UNAVAILABLE_MESSAGE = "The safety check is unavailable right now, so your request was not processed. Please try again."
# Used when FLYYY rejected the agent's keys: retrying will not help, the agent's
# configuration has to be fixed.
DEFAULT_REJECTED_MESSAGE = (
    "This assistant's safety check is not configured correctly, so your request was not processed. "
    "Please contact the administrator."
)
REDACTED_INPUT = "[Removed: blocked by FLYYY guard]"


def _text_of(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _session_id() -> Optional[str]:
    try:
        from langgraph.config import get_config

        thread_id = (get_config().get("configurable") or {}).get("thread_id")
        return str(thread_id) if thread_id is not None else None
    except Exception:  # outside a graph run, or no config
        return None


class FlyyyGuardMiddleware(AgentMiddleware):
    """Checks the user's prompt once, before the agent starts.

    One FLYYY check per `agent.invoke(...)`: the user's new message is checked before the
    agent runs. If FLYYY flags it, the run ends with `block_message` and neither the model
    nor any tool is called; otherwise the agent runs normally with no further checks.
    Every check (allowed or blocked) is recorded in FLYYY's Guardrails view.

    To also check tool results (injection hidden in retrieved documents), add
    `FlyyyToolOutputGuardMiddleware()` as well; it checks before each model call.
    """

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        block_message: str = DEFAULT_BLOCK_MESSAGE,
        unavailable_message: str = DEFAULT_UNAVAILABLE_MESSAGE,
        rejected_message: str = DEFAULT_REJECTED_MESSAGE,
        redact_blocked: bool = True,
        fail_open: Optional[bool] = None,
        timeout: Optional[float] = None,
        client: Optional[FlyyyGuardClient] = None,
    ):
        super().__init__()
        self.client = client or FlyyyGuardClient(url, api_key, timeout=timeout, fail_open=fail_open)
        self.block_message = block_message
        self.unavailable_message = unavailable_message
        self.rejected_message = rejected_message
        self.redact_blocked = redact_blocked

    def _pending(self, messages: list[AnyMessage]) -> list[tuple[AnyMessage, Source]]:
        """User messages added since the last model response (newest last)."""
        pending: list[tuple[AnyMessage, Source]] = []
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                break
            if isinstance(message, HumanMessage):
                pending.append((message, "user_input"))
        pending.reverse()
        return pending

    def _blocked_update(self, message: AnyMessage, decision: GuardDecision) -> dict[str, Any]:
        updates: list[AnyMessage] = []
        if self.redact_blocked and message.id:
            # Same id replaces the stored message, so the blocked text never reaches the model
            # on later turns of the same conversation (checkpointer history).
            if isinstance(message, ToolMessage):
                updates.append(ToolMessage(content=REDACTED_INPUT, tool_call_id=message.tool_call_id, id=message.id))
            else:
                updates.append(HumanMessage(content=REDACTED_INPUT, id=message.id))
        if decision.credentials_rejected:
            content = self.rejected_message
        elif decision.error:
            content = self.unavailable_message
        else:
            content = self.block_message
        updates.append(
            AIMessage(
                content=content,
                response_metadata={
                    "flyyy_guard": {
                        "blocked": True,
                        "attack_type": decision.attack_type,
                        "risk_score": decision.risk_score,
                        "request_id": decision.request_id,
                        "error": decision.error,
                    }
                },
            )
        )
        return {"messages": updates, "jump_to": "end"}

    def _evaluate(self, state: AgentState) -> Optional[dict[str, Any]]:
        session_id = _session_id()
        for message, source in self._pending(state.get("messages") or []):
            decision = self.client.check(_text_of(message), session_id=session_id, source=source)
            if not decision.allowed:
                logger.info(
                    "flyyy-guard: blocked %s (attack_type=%s, risk=%.2f, request_id=%s)",
                    source, decision.attack_type, decision.risk_score, decision.request_id,
                )
                return self._blocked_update(message, decision)
        return None

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        return self._evaluate(state)

    @hook_config(can_jump_to=["end"])
    async def abefore_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._evaluate, state)


class FlyyyToolOutputGuardMiddleware(FlyyyGuardMiddleware):
    """Optional: checks tool results before each model call (indirect prompt injection).

    Use together with `FlyyyGuardMiddleware`. Adds one FLYYY check per tool result.
    """

    def _pending(self, messages: list[AnyMessage]) -> list[tuple[AnyMessage, Source]]:
        pending: list[tuple[AnyMessage, Source]] = []
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                break
            if isinstance(message, ToolMessage):
                pending.append((message, "tool_output"))
        pending.reverse()
        return pending

    # Runs before each model call instead of once before the agent.
    before_agent = AgentMiddleware.before_agent
    abefore_agent = AgentMiddleware.abefore_agent

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        return self._evaluate(state)

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._evaluate, state)
