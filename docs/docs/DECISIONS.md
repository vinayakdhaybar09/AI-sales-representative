# DECISIONS

## Locked (do not change without the owner's explicit approval)
| Area | Decision |
|---|---|
| Language | English only |
| Responses | Single JSON response, no streaming |
| Users | Guests identified by `conversation_id` only |
| Framework | Async FastAPI for network-bound code; plain `def` for pure logic |
| Packaging | `pip` + venv + `requirements.txt` (no Docker, no uv, no Poetry) |
| Chat model | `mistral-small-latest` is the default in code; the owner's free key has 0 req/min on it, so `.env` sets `CHAT_MODEL=open-mistral-nemo` (approved in M2) |
| Embeddings | `mistral-embed`, 1024 dims. Hugging Face is fallback only |
| Orchestration | LangGraph for workflow, LangChain as model/embedding/retrieval abstraction |
| Business logic | SQL, filters, tray building, validation, sufficiency in Python, not prompts |
| Stock | Out-of-stock products are never excluded, but they are demoted: in-stock first, and an out-of-stock product is never the single pick while an in-stock one exists (approved 2026-10-28); tray has `availability` |
| Support | RAG over support data only; no live order API |
| Sufficiency Check | Plain Python rules |
| Validator | Deterministic; one Composer retry, then fallback |
| Data | Used as-is; no cleaning; contradictions deferred |
| Testing | `curl` + scripts + phase checklists; no tracing, no advanced suites. Exception (approved 2026-10-28): one summary log line per turn (model calls, timings, validation issues) and `scripts/replay_conversations.py`; nothing is stored in the database |
| Backend/DB | Direct PostgreSQL access via repository layer; no internal API layer |

## Proposed defaults (not yet locked; the agent may use them, and flag if it deviates)
- **DB driver**: `psycopg` v3 async + `psycopg_pool`, raw SQL in repositories (no ORM), `pgvector` Python package for vector adaptation. Verify current docs before using.
- **Structured output**: LangChain `with_structured_output(PydanticModel)` on the Mistral chat model for Query Understanding.
- **Top-k**: 20 candidates for product search, 5 chunks for blog/support; tune later.
- **Retry/backoff** for Mistral free-tier rate limits is added in Phase 13, not earlier.
- **Conversation history passed to LLM**: last ~6 messages plus `pending_clarification`; finalize in Phase 8/9.
- **Optional tiny pytest tests** for pure functions only (sufficiency rules, validator, tray builder).

## How to propose a change
State the problem, the alternative, and the cost, in your final message. Do not implement the alternative until approved.
