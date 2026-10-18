# PHASES

Phases 1–4 are done. The remaining work is grouped into five milestones. Work one milestone at a time: implement fully → run → give the owner a TEST GUIDE → stop. Do not start the next milestone until the owner reports results. Update the status table as milestones are verified.

| # | Phase / Milestone | Status |
|---|---|---|
| 1 | Setup + `/health` | Verified |
| 2 | Schemas, service layer, stub `/api/chat` | Verified |
| 3 | Config, env vars, logging | Verified |
| 4 | Neon + pgvector + `products` table + product ingestion | Verified |
| M1 | Embeddings + vector search (old 5–6) | Verified |
| M2 | Query Understanding + LangGraph skeleton, in-memory state (old 7–8) | Verified |
| M3 | Sufficiency, clarification, out-of-scope, all four specialists (old 9–10) | In progress |
| M4 | Composer, validator, retry-once, fallback, tray builder, real `handle_chat` (old 11) | Not started |
| M5 | Conversation persistence, session expiry, error handling, retries, error envelope (old 12–13) | Not started |

## Completed phase 4 (reference)
Build: `app/db/connection.py` (async pool, opened/closed in `lifespan`), `app/db/schema.sql` (`CREATE EXTENSION vector`, `products`, `embeddings` tables), `app/db/repositories/products.py`, `scripts/ingest_products.py`, `/health` with a DB check.
Done when: extension enabled; products table filled from `data/bombay-shaving-product-data.json` (idempotent upsert); a script/endpoint reads products by ID and by category; `DATABASE_URL` missing gives a clear error at first DB use, not at startup.

## Milestone details

### M1. Embeddings + vector search
Build: `app/llm/models.py` embedding factory; `scripts/ingest_embeddings.py` for all three sources per `docs/DATA.md`; `app/retrieval/` search helper (cosine distance, `source_type` filter, top-k) and a dev-only search route or script.
Done when:
- `embeddings` rows counted per `source_type`; re-running does not duplicate rows; batching handles rate limits.
- Sample queries ("patchy beard", "sensitive skin razor", "where is my order") return relevant rows from the correct source only.

### M2. Query Understanding + LangGraph skeleton
Build: chat model factory, `app/schemas/query.py`, prompt in `app/llm/prompts/`, a node/function returning the structured output, dev script to try messages. `app/graph/state.py`, `builder.py`, `nodes/` with stub specialists/composer; `handle_chat` calls the graph; in-memory conversation store.
Done when:
- Varied messages (incl. out-of-scope, vague, product-named, follow-up with state) yield valid `{intent, scope, entities, filters, context}`.
- `/api/chat` flows through the graph end-to-end with correct routing for each branch (out-of-scope, insufficient, each intent), still returning a valid envelope.

### M3. Sufficiency, clarification, out-of-scope, specialists
Build: Python sufficiency rules, clarification question generation (one question), `pending_clarification` handling, predefined suggested-prompts list, out-of-scope response. Specialists in order knowledge → support → recommendation → comparison, each returning the common specialist output structure. Apply the trimmer-ambiguity rule from `docs/DATA.md` in support.
Done when:
- "Suggest a trimmer" gets one clarifying question; the answer resumes the original request; an unrelated message discards the pending clarification; no clarification loops.
- Each specialist returns correct structured data (with sources and warnings) for sample queries; out-of-stock products appear.

### M4. Composer, validator, tray, real `handle_chat`
Build: `app/response/composer.py`, `validator.py`, `envelope.py`; tray builder in Python; retry-once; fallback; `handle_chat` fully wired to the graph (stub logic deleted).
Done when: tray always equals specialist products with exact IDs/names/prices/URLs/availability; forcing a bad composition triggers one retry then fallback.

### M5. Persistence + hardening
Build: conversation tables + repository; session expiry (~10–15 min inactivity); error classes/handlers, envelope errors (including 422s), Mistral retry/backoff, timeouts, key-switch note.
Done when:
- A conversation (including `pending_clarification`) survives a server restart.
- Failures return `{"success": false, "error": {...}}`, never stack traces.

## Milestone report template (final message of each milestone)
```
Milestone Mn — summary
Files created/changed: ...
Verification: [ ] done-when item — result ...
Not tested / assumptions: ...
Flagged conflicts: ...

TEST GUIDE
Commands: exact command → expected output (each)
Sample chat messages (3–5): message → what a correct response looks like
Try to break it (2–3): action → expected safe behavior
```
