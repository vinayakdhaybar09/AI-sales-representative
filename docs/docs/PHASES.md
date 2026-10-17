# PHASES

Work one phase at a time. Implement → run → verify against the checklist → report → stop. Do not start the next phase until the owner confirms. Update the status table below as phases are verified.

| # | Phase | Status |
|---|---|---|
| 1 | Setup + `/health` | Verified |
| 2 | Schemas, service layer, stub `/api/chat` | Verified |
| 3 | Config, env vars, logging | Written; awaiting owner's verification |
| 4 | Neon + pgvector + `products` table + product ingestion | Next |
| 5 | Embeddings for products, blogs, support | Not started |
| 6 | Vector search endpoint (no LLM) | Not started |
| 7 | LLM integration + Query Understanding | Not started |
| 8 | LangGraph skeleton (stub nodes, conditional routing, in-memory state) | Not started |
| 9 | Sufficiency Check + Clarification + Out-of-Scope | Not started |
| 10 | Specialists: knowledge → support → recommendation → comparison | Not started |
| 11 | Composer, Validator, retry-once, fallback | Not started |
| 12 | Conversation persistence + session expiry (Postgres) | Not started |
| 13 | Error handling and hardening (retries, rate limits, error envelope) | Not started |

## Phase details

### 4. Database + products
Build: `app/db/connection.py` (async pool, opened/closed in `lifespan`), `app/db/schema.sql` (`CREATE EXTENSION vector`, `products`, `embeddings` tables), `app/db/repositories/products.py`, `scripts/ingest_products.py`, `/health` extended with a DB check.
Done when: extension enabled; products table filled from `data/bombay-shaving-product-data.json` (idempotent upsert); a script/endpoint reads products by ID and by category; `DATABASE_URL` missing gives a clear error at first DB use, not at startup.

### 5. Embeddings
Build: `app/llm/models.py` embedding factory, `scripts/ingest_embeddings.py` for all three sources per `docs/DATA.md`.
Done when: `embeddings` rows counted per `source_type`; re-running does not duplicate rows; batching handles rate limits.

### 6. Vector search (no LLM)
Build: `app/retrieval/` search helper (cosine distance, `source_type` filter, top-k) and a dev-only search route or script.
Done when: sample queries ("patchy beard", "sensitive skin razor", "where is my order") return relevant rows from the correct source only.

### 7. Query Understanding
Build: chat model factory, `app/schemas/query.py`, prompt in `app/llm/prompts/`, a node/function returning the structured output; dev script to try messages.
Done when: varied messages (incl. out-of-scope, vague, product-named, follow-up with state) yield valid `{intent, scope, entities, filters, context}`.

### 8. LangGraph skeleton
Build: `app/graph/state.py`, `builder.py`, `nodes/` with stub specialists/composer; `handle_chat` calls the graph; in-memory conversation store.
Done when: `/api/chat` flows through the graph end-to-end with correct routing for each branch (out-of-scope, insufficient, each intent), still returning a valid envelope.

### 9. Sufficiency, Clarification, Out-of-Scope
Build: Python sufficiency rules, clarification question generation (one question), `pending_clarification` handling, predefined suggested-prompts list.
Done when: "Suggest a trimmer" gets one clarifying question; the answer resumes the original request; an unrelated message discards the pending clarification; no clarification loops.

### 10. Specialists (one at a time, each verified before the next)
Order: knowledge → support → recommendation → comparison. Each returns the common specialist output structure. Apply the trimmer-ambiguity rule from `docs/DATA.md` in support.
Done when: each returns correct structured data (with sources and warnings) for sample queries; out-of-stock products appear.

### 11. Composer + Validator
Build: `app/response/composer.py`, `validator.py`, `envelope.py`; tray builder in Python; retry-once; fallback.
Done when: tray always equals specialist products with exact IDs/names/prices/URLs/availability; forcing a bad composition triggers one retry then fallback.

### 12. Persistence
Build: conversation tables + repository; session expiry (~10–15 min inactivity).
Done when: a conversation (including `pending_clarification`) survives a server restart.

### 13. Hardening
Build: error classes/handlers, envelope errors (including 422s), Mistral retry/backoff, timeouts, key-switch note.
Done when: failures return `{"success": false, "error": {...}}`, never stack traces.

## Phase report template (final message of each phase)
```
Phase N — summary
Files created/changed: ...
How to run: ...
Verification: [ ] item — result ...
Not tested / assumptions: ...
Questions or flagged conflicts: ...
```
