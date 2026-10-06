"""flyyy-guard: block prompt injection before it reaches your LLM, using FLYYY's guardrail check."""

__version__ = "0.1.0"

from flyyy_guard.client import (  # noqa: E402
    FlyyyGuardClient,
    GuardDecision,
    PromptBlockedError,
    check,
    check_or_raise,
)

__all__ = [
    "FlyyyGuardClient",
    "FlyyyGuardMiddleware",
    "GuardDecision",
    "PromptBlockedError",
    "check",
    "check_or_raise",
    "__version__",
]


def __getattr__(name: str):
    # Imported lazily so `pip install flyyy-guard` works without LangChain.
    if name == "FlyyyGuardMiddleware":
        from flyyy_guard.middleware import FlyyyGuardMiddleware

        return FlyyyGuardMiddleware
    raise AttributeError(f"module 'flyyy_guard' has no attribute {name!r}")
