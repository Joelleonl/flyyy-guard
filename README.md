# flyyy-guard

Block prompt injection **before it reaches your LLM**, using FLYYY's guardrail check.

Every user prompt (and, by default, every tool result) is sent to FLYYY's
`/api/v1/guardrails/check` endpoint before the model runs. If FLYYY flags it, the agent
stops and returns a refusal; the model is never called. Every check shows up in
FLYYY → AI Governance → GenAI Governance → your project → **Guardrails**.

## Quickstart (LangChain `create_agent`)

1. Install:
   ```bash
   pip install "flyyy-guard[langchain]"
   ```
2. Add to your `.env` (the key comes from FLYYY → GenAI Governance → your project → Guardrails):
   ```
   FLYYY_URL=https://<your-flyyy-backend>
   FLYYY_GUARDRAIL_KEY=fg_xxxxxxxx
   ```
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
| `FlyyyGuardMiddleware(check_tool_outputs=False)` | `True` | Only check user messages, not tool results |
| `FlyyyGuardMiddleware(redact_blocked=False)` | `True` | Keep the blocked text in conversation history |
| `FLYYY_GUARD_FAIL_OPEN=true` / `fail_open=True` | off | If FLYYY is unreachable, allow instead of block |
| `FLYYY_GUARD_TIMEOUT=3` / `timeout=3` | 3 seconds | How long to wait for FLYYY |

A rejected or revoked guardrail key always blocks, whatever the fail-open setting, so a
misconfiguration is noticed instead of silently turning protection off.

## Privacy

The guard sends only the text being checked and the session id. It never logs your key
or the prompt text. FLYYY stores a short preview of each checked input for the Guardrails view.
