# AGENTS.md — BSC AI Sales Representative (backend)

Read this file fully before writing any code. It is the entry point; details live in `docs/`.

## What this project is
Backend for an AI sales assistant for **Bombay Shaving Company (BSC)**. A user sends a natural-language message; the backend returns Markdown, an optional product tray (product cards), and optional suggested prompts. It handles four intents: `recommendation`, `comparison`, `knowledge`, `support`. Anything unrelated to BSC is politely declined (`out_of_scope`).

Stack: Python 3.11+, FastAPI, Uvicorn, Pydantic v2 / pydantic-settings, LangChain (model/embedding/retrieval abstraction), LangGraph (workflow), Neon PostgreSQL + pgvector, Mistral (`mistral-small-latest` chat, `mistral-embed` 1024-dim embeddings). Hugging Face is a **fallback only**. Frontend (separate repo) is React + `react-markdown`.

## Read these before the relevant work
| File | Read when |
|---|---|
| `docs/ARCHITECTURE.md` | Any graph, node, specialist, composer, validator work |
| `docs/CONTRACTS.md` | Any schema, API, state, or JSON shape. **Contracts are fixed; do not change them silently** |
| `docs/DATA.md` | Any DB, ingestion, embedding, retrieval work. Includes known data quirks |
| `docs/DECISIONS.md` | Before proposing any alternative tool, pattern, or scope change |
| `docs/PHASES.md` | To find the current phase, its deliverables, and its verification checklist |

## Hard rules (never violate)
1. **Layering.** API routes → service → graph nodes → specialists → repositories/retrievers → DB. A layer must not reach past the one below it. Routes know HTTP only; repositories know SQL only; retrievers know vector search only; the `llm/` module is the only place that builds models.
2. **Business logic is Python, not prompts.** SQL, metadata filtering, sufficiency rules, product-tray construction, and validation are plain Python. LLMs only do: query understanding (structured output), composing Markdown, and generating one clarification question.
3. **The `products` table is the single source of truth** for price, availability, URL, image, and product details. Embeddings only *discover* candidate IDs. Never take price/availability/URL from embedding metadata or from LLM output.
4. **The product tray is built in Python from specialist output.** The Composer LLM never writes tray fields. The tray may contain only products present in the Recommendation Specialist result.
5. **Never invent** product names, prices, features, policies, URLs, or contact details. Use only what specialists returned.
6. **Out-of-stock products are never filtered out.** Each tray card carries `availability` (`in_stock` | `out_of_stock`); Markdown marks out-of-stock items "Currently out of stock".
7. **Support has no live data.** No order status, delivery date, refund status, or order contents can be claimed. Give general guidance from support data plus the tracking link and care email found in that data.
8. **Validator is deterministic**: no LLM, no extra API calls. One Composer retry on critical failure, then the `fallback` response. Never retry more than once.
9. **Clarify at most once per request.** Never loop on clarification questions.
10. **Secrets.** `.env` is never committed. Keys are `SecretStr`; call `.get_secret_value()` in exactly one place (the `llm/models.py` / `db/connection.py` factory). Never log secrets.
11. **Logging.** Use `logging.getLogger(__name__)`, `%s` placeholders. Log message **length** at INFO; message **content** only at DEBUG.
12. **Async.** Anything touching the network (LLM, embeddings, DB) is `async def` and awaited (`ainvoke`, `aembed_*`). Pure logic (filters, validators, tray builders) is plain `def`.
13. **Do not verify LangChain / LangGraph / Mistral / pgvector / psycopg APIs from memory.** Check current official docs (web search/fetch) before using them, pin versions in `requirements.txt`, and say what you could not run.
14. **Data is used as-is.** Do not clean or "fix" the datasets or support-data contradictions (see `docs/DATA.md` → Known issues). Surface them, do not resolve them.

## Existing code conventions (Phases 1–3 are already built)
- Layout: `app/{main.py, api/routes/, core/, schemas/, services/, graph/, specialists/, llm/, db/, retrieval/, response/}`; `data/` holds the four JSON files; `scripts/` holds one-off scripts (run as `python -m scripts.<name>` from project root).
- Config: `from app.core.config import get_settings` (cached `Settings`). Never call `os.getenv` or instantiate `Settings()` directly.
- Schemas: Pydantic models in `app/schemas/`. `ChatRequest`, `ChatEnvelope`, `ChatResponseBody`, `ProductCard`, `ErrorInfo` already exist in `app/schemas/chat.py`.
- `app/services/chat_service.py::handle_chat(request) -> ChatEnvelope` is currently a **stub**. Its signature stays; its body is replaced by a call to the LangGraph workflow (Phase 8+). Delete the stub logic when replaced.
- Settings fields: `app_env, log_level, mistral_api_key, huggingface_api_key, database_url, chat_model, embedding_model, embedding_dimensions`.
- Dependencies: `pip` + venv + `requirements.txt` (`pip freeze > requirements.txt` after installing). No Docker, no uv, no Poetry.

## How to work
- **One phase at a time** (see `docs/PHASES.md`). Implement the phase fully, run its verification, report results, then stop. Do not write code for later phases.
- Create folders/files only when the current phase needs them.
- Prefer small, readable functions over clever abstractions. The owner is a frontend developer new to RAG and must be able to read and modify the code: add short docstrings explaining *why*, not just *what*.
- Verification is `curl` + scripts + the phase checklist. No tracing, no heavy test suites. Optional: tiny `pytest` tests for pure-Python logic (sufficiency rules, validator, tray builder).
- When something is ambiguous or conflicts with these docs, **ask or flag it** in your final message instead of choosing silently. If you change a contract, update `docs/CONTRACTS.md` in the same change.
- Final message of each phase: what changed (files), how to run, verification results (pass/fail per checklist item), what you could not test, and any assumptions.

## Commands
```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload                 # run API (restart manually after editing .env)
python -m scripts.check_config                # show what settings the app sees
curl http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message":"Suggest a razor for sensitive skin","conversation_id":"guest_1"}'
```

## Out of scope for the MVP (do not build)
Other languages, streaming, logins/long-term user history, live order or inventory APIs, tracing/observability, advanced test suites, data cleaning, an internal API layer between backend and DB.
