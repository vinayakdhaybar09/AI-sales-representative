# ARCHITECTURE

## Layers
```
Frontend → FastAPI POST /api/chat (HTTP only)
        → Chat Service (runs graph, shapes errors)
        → LangGraph workflow (state, routing)
             → Specialists (what to retrieve)
                  → Repositories (SQL)  +  Retrievers (pgvector)  → Neon Postgres
             → Composer / Validator / Envelope (response/)
        LLM module (llm/models.py, llm/prompts/) is used only by nodes that need a model
```
| Layer | Knows | Must NOT know |
|---|---|---|
| API routes | HTTP, schemas | LLMs, SQL, graph internals |
| Service | calling graph, error shaping | HTTP details, SQL |
| Graph nodes | state, routing | HTTP, raw SQL |
| Specialists | what to retrieve per intent | final phrasing |
| Repositories | SQL | LLMs |
| Retrievers | vector search | business rules |
| LLM module | models, prompts | database |

Swapping the scraped product data for a real BSC API must only require changing the product repository.

## Request flow
1. Frontend sends `{message, conversation_id}`.
2. Route validates (Pydantic) → service invokes graph.
3. **Session loader**: load conversation state for the ID (may contain `pending_clarification`).
4. **Query Understanding** (LLM, structured output) → `{intent, scope, entities, filters, context}`.
5. Route: `out_of_scope` → Out-of-Scope Handler → Envelope. Else → **Sufficiency Check** (Python).
   - Insufficient → Clarification Handler → Envelope.
   - Sufficient → Specialist(s).
6. **Specialists** return `{specialist, status, data, sources, warnings}`. One query may use several (e.g. recommendation + knowledge).
7. **Composer** (LLM) writes Markdown from specialist output only; `product_tray` is built in Python.
8. **Validator** (deterministic) compares response to specialist output. Critical failure → Composer runs once more with (specialist output, previous response, issues) → Validator again → still invalid → `fallback`.
9. **Envelope** wraps into final JSON. State is saved.

```
Load state → Query Understanding ─┬→ Out-of-Scope Handler ─────────────┐
                                  ↓ in scope                          │
                           Sufficiency Check                          │
                            ├ insufficient → Clarification Handler ───┤
                            ↓ sufficient                              │
                  Specialist(s) → Composer ⇄ Validator (retry once) ──┤
                                   └ still invalid → fallback ────────┤
                                                                      ↓
                                                              Response Envelope
```
Clarification and out-of-scope **skip** Specialist → Composer → Validator (they make no product/knowledge/support claims).

## Clarification handling
- On insufficiency, store `pending_clarification` in state: `{original_query, intent, missing_field, question, attempt_count}`.
- Next message goes through Query Understanding with that history:
  - answers the clarification → merge with `original_query` → Specialist (do not clarify again);
  - new unrelated request → discard pending clarification, process as new.
- No follow-up flag in the request; detection uses conversation history + the new message. The Query Understanding model reports `context.answers_pending_clarification`; Python then merges `original_query` with the answer for retrieval and skips the sufficiency check (never clarify twice).
- Clarification response: `type="clarification"`, one focused question, empty `product_tray`, optional `suggested_prompts`.

## Sufficiency Check (plain Python; proposed defaults, refine in Phase 9)
| Intent | Sufficient when |
|---|---|
| recommendation | a product category, OR a concern/use case/skin type is present |
| product_finalization | products were already shown in this conversation; otherwise the recommendation rules above (the specialist then searches first) |
| comparison | at least two product references resolvable from query/context |
| knowledge | a topic/entity/question subject is present |
| support | always sufficient (RAG handles breadth) |

Clarify on the single most decisive missing field (e.g. trimmer → `use_case`: beard / body / both).

## Specialists (each returns data, never final prose)
- **Recommendation**: semantic search over product embeddings (top-k) → candidate product IDs → SQL lookup in `products` → apply filters (budget, category, gender, etc.) → rank (default: similarity order) → full product records. May pull blog chunks for context.
- **Product finalization**: narrows options down to the best 1–3 (`filters.result_limit`). Candidates = the products shown earlier (the saved pool); with no pool, or when the criteria rule out all of it, it runs the recommendation search and picks from that. Python picks (budget/exclusions → in-stock only → priority or a quality score from review-weighted rating, fit to stated needs and match score) and writes `selection_reasons`; the Composer only explains. The tray holds the pick(s) as featured cards (rank, description, benefits, how to use). Details: `docs/CONTRACTS.md`.
- **Comparison**: resolve 2+ products (direct SQL by name/ID match, embeddings as fallback) → structured comparison fields from `products`.
- **Knowledge**: blog-chunk semantic search (`source_type='blog'`) + product info via SQL when a product is named.
- **Support**: semantic search over `source_type='support'` (FAQs + policies). No order lookup. Return the tracking link and `care@bombayshavingcompany.com` as found in the retrieved data.

Specialist `status`: `success | empty | error`. `warnings` carries things like "trimmer model not identified" (see `docs/DATA.md`).

## Composer rules
- Markdown compatible with `react-markdown`; concise; uses only specialist data.
- Product IDs, image URLs, product URLs stay in structured fields, not in Markdown prose.
- Recommendation → Markdown + tray. Comparison → Markdown table (no separate frontend structure). Knowledge/Support → Markdown. Non-recommendation → empty tray.
- Mark out-of-stock items "Currently out of stock".
- Never claim customer-specific order/refund/delivery status.

## Validator
**Critical (trigger retry):** response structure/type valid; tray product IDs, names, prices, image URLs, product URLs, availability match specialist output; tray ⊆ specialist products; comparison values match; support contact/policy values match.
**Non-critical (log only):** Markdown quality, optional badges, optional source metadata, wording.
Implemented checks (`app/response/validator.py`): type/structure, non-empty Markdown, no raw HTML/CSS markup, tray equals specialist products field by field (empty for non-recommendation), every ₹ amount / URL / email in the Markdown exists in the specialist data, a bolded catalog product not in the result, out-of-stock product without "Currently out of stock", customer-specific order claims. It is heuristic and cannot prove every sentence is grounded.
Specialist `empty` results get a fixed reply (`app/response/empty_replies.py`, no LLM, no validation); `error` results go straight to `fallback`.

## Conversation state
Stored in Postgres (`conversations` table, `app/graph/conversation_store.py`). Besides the last 12 messages (assistant turns stored compactly) it keeps the product pool of the last recommendation, the latest finalized pick, and `preferences`: structured memory merged in Python (`app/graph/preferences.py`) from each turn's extracted entities/filters, so early needs ("sensitive skin") are not forgotten when old messages drop out of the window. A conversation idle longer than `CONVERSATION_TTL_MINUTES` (default 15) is treated as new and deleted; a storage failure never blocks an answer. Pass only *relevant* recent history to the LLM, not everything. Expire inactive conversations after ~10–15 minutes (details in Phase 12).

## Out-of-scope / suggested prompts
Suggested prompts come from a **small predefined list** of BSC questions (not freely generated). Out-of-scope shows 1–2 of them.
