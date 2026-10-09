# flyyy-guard

Block prompt injection **before it reaches your LLM**, using FLYYY's guardrail check.

The user's prompt is sent once to FLYYY's `/api/v1/guardrails/check` endpoint before the
agent starts, where an LLM judge decides whether it is a prompt injection. If it is, the
agent stops and returns a refusal; neither the model nor any tool is called. Otherwise the
agent runs normally with no further checks. Every check shows up in
FLYYY → AI Governance → GenAI Governance → your project → **Guardrails**.

## Quickstart (LangChain `create_agent`)

1. Install:
   ```bash
   pip install "flyyy-guard[langchain]"
   # or, in a uv project
   uv add "flyyy-guard[langchain]"
   ```
2. Add `FLYYY_URL` to the `.env` that already holds your project's Langfuse keys. The guard
   authenticates with those same keys, so no extra key is needed:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   FLYYY_URL=https://<your-flyyy-backend>
   ```
   If you were given a guardrail key (`FLYYY_GUARDRAIL_KEY=fg_...`), it is used instead.
3. Add the middleware where you create the agent:
   ```python
   from flyyy_guard import FlyyyGuardMiddleware

   agent = create_agent(
       model=model,
       tools=tools,
       system_prompt=system_prompt,
       checkpointer=checkpointer,
       middleware=[FlyyyGuardMiddleware()],
   )
   ```

Nothing else changes: `agent.invoke(...)`, your Langfuse `CallbackHandler`, tools and prompts stay as they are.
The conversation's `thread_id` is sent as the session id automatically.

When a prompt is blocked, `agent.invoke` returns normally and the last message is
`"Your request was blocked by policy."`. Its `response_metadata["flyyy_guard"]` holds the
attack type, risk score and FLYYY request id. The blocked text is replaced in the stored
conversation so it is never sent to the model on later turns.

## Any other framework

```bash
pip install flyyy-guard
```
```python
from flyyy_guard import check

decision = check(user_prompt, session_id=session_id)
if not decision.allowed:
    return "Your request was blocked by policy."
response = llm.invoke(user_prompt)
```
`check_or_raise(...)` does the same but raises `PromptBlockedError`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `FlyyyGuardMiddleware(block_message=...)` | `"Your request was blocked by policy."` | Reply returned when blocked |
| `FlyyyGuardMiddleware(unavailable_message=...)` | `"The safety check is unavailable right now..."` | Reply when the check itself failed (FLYYY unreachable, timeout, server error) |
| `FlyyyGuardMiddleware(rejected_message=...)` | `"This assistant's safety check is not configured correctly..."` | Reply when FLYYY rejected the agent's keys (wrong, revoked, or from another Langfuse) |
| `FlyyyToolOutputGuardMiddleware()` (add to `middleware=[...]`) | not used | Also check every tool result before the model reads it (one extra check per tool result) |
| `FlyyyGuardMiddleware(redact_blocked=False)` | `True` | Keep the blocked text in conversation history |
| `FLYYY_GUARD_FAIL_OPEN=true` / `fail_open=True` | off | If FLYYY is unreachable, allow instead of block |
| `FLYYY_GUARD_TIMEOUT=10` / `timeout=10` | 10 seconds | How long to wait for FLYYY |

A rejected or revoked guardrail key always blocks, whatever the fail-open setting, so a
misconfiguration is noticed instead of silently turning protection off.

## Privacy

The guard sends only the text being checked and the session id. It never logs your key
or the prompt text. FLYYY stores a short preview of each checked input for the Guardrails view.
