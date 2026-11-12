# CONTRACTS (fixed shapes — change only deliberately, and update this file)

## POST /api/chat
Request:
```json
{ "message": "Suggest a razor for sensitive skin", "conversation_id": "guest_8c36b3ac-..." }
```
Constraints: `message` 1–1000 chars (whitespace stripped); `conversation_id` 1–100 chars. Invalid input → 422 before our code runs.

Response envelope (always these four keys):
```json
{
  "success": true,
  "conversation_id": "guest_8c36b3ac-...",
  "response": {
    "type": "recommendation",
    "markdown": "...",
    "product_tray": [
      { "product_id": "8447139315866", "name": "...", "price": 450.0,
        "image_url": "https://...", "product_url": "https://...", "availability": "in_stock",
        "rating": 4.79, "review_count": 202, "original_price": 149.0,
        "rank": null, "description": null, "key_benefits": [], "selection_reasons": [] }
    ],
    "comparison_table": null,
    "suggested_prompts": []
  },
  "error": null
}
```
- `type` ∈ `recommendation | product_finalization | comparison | knowledge | support | clarification | conversation | fallback`.
- `availability` ∈ `in_stock | out_of_stock` (a deliberate addition to the original design doc).
- `rating`, `review_count`, `original_price` on tray cards are optional (null): rating/review_count are null when the product has no reviews (never 0.0); `original_price` is set only when higher than `price`. All come from the `products` table.
- `product_tray` is non-empty only for `recommendation` (up to 5 cards) and `product_finalization` (1–3 cards). Every other response type: `[]` (a comparison has no tray: its table header carries the products).
- **Comparison table** (`type: "comparison"` only; `null` everywhere else, and `null` when fewer than two products could be resolved): `{ "products": ProductCard[2..3], "rows": [{ "key", "label", "cells": [[str, ...], ...] }] }`. Built in Python (`app/response/comparison_table.py`), never by the model. `products` are the columns (image, name, price, availability, rating, URLs, same fields as a tray card); every row has one cell per product, in column order; a cell is a list of short lines and `[]` means "no data" (the frontend shows a dash). Rows come in a fixed order and a row nobody has data for is dropped: `price` (second line `was ₹X · save N%` for a real discount), `availability`, `rating` (`No ratings yet` without reviews), `description`, `benefits`, `features`, then a `spec:weight_grams` row (Weight) when at least two products have it; internal fields (sku, barcode) are never shown. The markdown of a comparison is only a short opener and a "pick X if…" verdict (a Markdown table in it is rejected by the validator). At most 3 products are compared; more are cut with warning `comparison_capped`.
- **Featured cards** (`type: "product_finalization"` only; always `null` / `[]` on `recommendation` cards): `rank` (1 = top pick, 2, 3), `description` (markup stripped, max ~500 chars), `key_benefits` (≤5 short strings: the product's benefits, or its features when it lists no benefits), `selection_reasons` (short factual strings saying why it was picked). Any of them can be empty (some products have no benefits text); the frontend hides empty sections.
- **Featured layout** (frontend): every card has the same size and structure (image with the View details / Add to cart buttons on the left, details on the right), shown in `rank` order in a horizontally scrollable tray, whether there are 1, 2 or 3 cards.
- Failure: `{"success": false, "conversation_id": "...", "response": null, "error": {"code": "...", "message": "..."}}` for every `/api/*` failure, including 422 (`conversation_id` is `""` if the body had none). HTTP status follows the code: `invalid_request` 422, `rate_limited` 429, `not_found` 404, `internal_error` 500, `upstream_unavailable` 503, `service_unavailable` 503, `upstream_timeout` 504. Messages are client-safe (no traces, keys or internals).
- `GET /health` → `{"status":"ok","service":"bsc-backend"}`.
- `GET /api/products/{product_id}` (digits only, else 422) → `{"success": true, "product": ProductDetail, "error": null}`; unknown id → 404 `not_found` in the standard error envelope. `ProductDetail` (`app/schemas/product.py`, built by `app/response/product_detail.py`): `product_id, name, category, price, original_price (only when higher), rating / review_count (null without reviews), availability, product_url, images[] (all stored images, de-duplicated, max 12, first = the card image), description, about (paragraphs separated by a blank line; markup and emoji removed), key_features[] (≤8; key features, else features), how_to_use[] (≤8 steps, numbering removed), other_information[{title, text}] (≤4), faqs[{question, answer}] (≤5), weight_grams`. Any list/text may be empty. It exists so the frontend preview panel can show everything we store without enlarging every chat reply; there are no per-customer review texts in our data.

Fallback response body (type, empty tray and prompts are fixed; the text depends on the reason):
```json
{ "type": "fallback",
  "markdown": "Good question! I can't confirm the details for Hair Removal Cream and Hair Removal Spray with confidence right now, so I won't guess. I can walk you through what each one is for, or look at something else, whichever helps.",
  "product_tray": [],
  "suggested_prompts": ["Suggest a trimmer for body grooming", "Compare two trimmers"] }
```
Reasons (`app/response/fallbacks.py`, templates only, no model call): `unverified` (the reply failed deterministic validation after the one revision), `service` (the model failed while writing), `specialist_error` (the lookup failed). For `unverified` the text names the products the customer was asking about (from the resolved request, or the products just shown for a comparison) or the category being discussed, otherwise it asks for a product or category. Product names always come from our own data. Support and knowledge questions never get product names.

## Query Understanding output (`app/schemas/query.py`)
```json
{ "intent": "recommendation|product_finalization|comparison|knowledge|support|conversation",
  "scope": "in_scope|out_of_scope",
  "entities": {},  "filters": {},  "context": {} }
```
- `entities`: products, category, use_case, body_area, attributes. `filters`: budget_max/min, skin_type, hair_type, gender, required features, exclusions, `result_limit`. `context`: carried-over info, e.g. `previously_mentioned_product_ids`.
- `product_finalization` = the user wants to narrow products already shown down to the best one or two ("narrow it down to your best option", "which one should I buy?", "just one, under ₹300"). It is chosen only when the message refers to earlier results; a fresh request for products stays `recommendation`, and comparing named products stays `comparison`.
- `filters.result_limit` (int 1–3 or null; used only by `product_finalization`): "best one" / "final pick" → 1, "top two" → 2, "shortlist" / "narrow it down to a few" → 3. Null means 1. Anything above 3 is capped at 3.
- `filters.priority` (`"lowest_price" | "highest_rated"` or null; used only by `product_finalization`): set when the user names what matters most ("cheapest one", "best rated"). Other criteria the user states ("under ₹300", "for sensitive skin", "lightweight") go into the existing `filters` / `entities` fields.
- Empty fields are fine. It extracts; it does **not** answer or judge sufficiency. It resolves references like "this product" using conversation state. Exact product matching happens in retrieval.
- `entities`, `filters`, `context` are typed Pydantic sub-models with all fields optional (an empty `{}` is still valid). `context.previously_mentioned_product_ids` is filled by Python from conversation state, never by the LLM. `context.answers_pending_clarification` (bool, default false) is set by the LLM only when the message answers the open clarification question.
- `resolved_request` (string; defaults to the message / search text): the message rewritten as one standalone sentence with references resolved ("this issue" → "dandruff", "the first two" → the two product names). `requirements` (list of ≤6 short strings): what a good answer must satisfy, including ones carried over from earlier turns. Both are filled by the LLM and read by the reviewer (`docs/ARCHITECTURE.md`); no specialist uses them to retrieve.
- `conversation` = greetings, thanks, how are you, who are you, bare acknowledgements, and anything unrelated to BSC. `out_of_scope` is a `scope` value (a hint), never an intent; both `scope = out_of_scope` and `intent = conversation` are answered by the conversation node with response `type: "conversation"` (no separate out-of-scope response type).
- Example: `{"intent":"recommendation","scope":"in_scope","entities":{"category":"trimmer","use_case":["body_grooming"]},"filters":{"budget_max":2000},"context":{"previously_mentioned_product_ids":[]}}`

## Pending clarification (in conversation state)
```json
{ "pending_clarification": { "original_query": "Suggest a trimmer", "intent": "recommendation",
  "missing_field": "use_case",
  "question": "What will you mainly use the trimmer for: beard grooming, body grooming, or both?",
  "attempt_count": 1,
  "result_limit": null } }
```
`result_limit` is saved so that "Suggest one final trimmer" → question → "beard grooming" still returns one product.

## Conversation state (`conversations` table via `app/graph/conversation_store.py`)
```json
{ "history": [{"role": "user", "content": "..."}],
  "previous_product_ids": ["8447139315866", "..."],
  "pool_search_text": "Suggest a trimmer for beard grooming",
  "pool_match_scores": { "8447139315866": 0.81 },
  "finalized_product_ids": ["8447139315866"],
  "preferences": { "category": "trimmer", "use_case": ["beard_grooming"], "skin_type": ["sensitive"],
                   "budget_max": 2000 },
  "pending_clarification": null }
```
- `history`: the last 12 messages. Assistant turns are stored compactly: "Showed products: A (₹x), B (₹y)" when a tray was shown, otherwise the reply cut to ~400 chars.
- `previous_product_ids` is the **candidate pool**: the tray of the most recent `recommendation` (or the candidates of a `product_finalization` that had to search fresh). `product_finalization` over an existing pool never overwrites it, so the user can narrow again ("and the second best?", "now only the cheapest") from the same pool.
- `pool_search_text` and `pool_match_scores` are saved with the pool so finalization can rank by how well each product fit the original need without a new search.
- `finalized_product_ids` is the latest pick (1–3 IDs). A new `recommendation` clears it.
- `preferences` is the **structured memory** of what the customer has told us, merged in Python after every in-scope turn from the extracted `entities` and `filters` (no extra LLM call): `category`, `use_case`, `body_area`, `skin_type`, `hair_type`, `gender`, `budget_min`, `budget_max`, `required_features`, `exclusions`. A new non-empty value replaces a single value; list values are added without duplicates (max 8). When the category changes, the need-specific fields (`use_case`, `body_area`, `required_features`, `exclusions`, `budget_min`, `budget_max`) are reset; personal fields (`skin_type`, `hair_type`, `gender`) are kept. It is passed to Query Understanding and used by `product_finalization`; nothing else reads it yet.
- If a `product_finalization` message arrives with no pool (new or expired conversation), the specialist runs the recommendation search itself and picks from those results (or, when required details are missing, the normal sufficiency/clarification rules apply first).

**Not stored:** `shown_products` (`[{id, name, category, picked}]`) is looked up from `previous_product_ids` by the session loader on every request. Query Understanding uses it to resolve "the first two", "the cream", "the second one" to exact product names, and the comparison specialist matches names against it before searching the catalogue.

## Specialist output (`app/schemas/specialist.py`)
```json
{ "specialist": "recommendation|product_finalization|comparison|knowledge|support",
  "status": "success|empty|error",
  "data": {}, "sources": [], "warnings": [] }
```
`data` differs by specialist:
- recommendation: `{products: [full products row + match_score]}` (max 5, similarity order, out-of-stock kept).
- product_finalization: `{products: [1–3 full rows + match_score + rank + selection_reasons], pool: [{id, match_score}], pool_source: "previous_results|new_search", ranking_basis: "priority|quality", criteria_applied: [...], requested: n}`. Selection is plain Python, never the LLM. The effective criteria are the current message's entities/filters, with gaps filled from `preferences`.
  1. Candidates: the saved pool when there is one; otherwise (or when the criteria rule out the whole pool) a fresh recommendation search with the same criteria (`pool_source: "new_search"`; the second case adds warning `widened_search`).
  2. Hard criteria on the `products` rows: budget and exclusions.
  3. In-stock products only; an out-of-stock product is returned only when no in-stock product qualifies (warning `selected_out_of_stock`). Out-of-stock items never pad a shorter list.
  4. Rank: by `filters.priority` when given (`lowest_price`, `highest_rated`); otherwise a quality score = review-weighted rating (a product with few reviews does not beat a well-reviewed one on rating alone) + fit to the stated needs (words from use case, skin/hair type, required features found in the product text) + the original `match_score`.
  5. Cut to the requested count (`filters.result_limit`); fewer qualifying products → warning `fewer_results_than_requested`.
  `selection_reasons` are short factual strings per product ("rated 4.8/5 from 202 reviews", "₹299, within your ₹300 budget", "in stock", "fits: sensitive skin") built in Python from the row. The Composer turns them into a salesperson-style explanation and may not add claims beyond the data. Nothing qualifies, even after the fresh search → `status: "empty"` with warning `no_products_match_criteria` (fixed reply, no LLM).
- comparison: `{products: [full rows], comparable_fields: [...], unresolved: [names]}`; one product per name the customer said (an ambiguous name compares the best match and adds a warning), at most 3 products in total.
- knowledge: `{chunks: [{source_id,title,heading,category,url,content,score}], products: [full rows for named products]}`.
- support: `{items: [{source_id,kind,category,content,score}], contact_info: {tracking_url, care_email}, live_order_data_available: false}`.
Warnings used so far: `trimmer_model_not_identified`, `shipping_charges_differ_between_sources`, `returns_wording_differs_between_sources`, `ambiguous_product_name`, `fuzzy_match`, `category_not_matched`, `no_products_within_budget`, `includes_out_of_stock`, `selected_out_of_stock`, `no_products_match_criteria`, `fewer_results_than_requested`, `widened_search`, `no_suitable_products`, `no_relevant_*`, `could_not_resolve_two_products`, `comparison_capped`, `specialist_failed`.

## Composer output (internal)
```json
{ "type": "recommendation", "markdown": "...", "product_tray": [],
  "metadata": { "specialists_used": [], "sources": [] } }
```
The envelope's `response` = `type, markdown, product_tray, comparison_table, suggested_prompts` (metadata stays internal).

## Reviewer verdict (`app/schemas/review.py`, internal)
```json
{ "fulfils": false,
  "issues": [ { "kind": "missing|unsupported|irrelevant", "detail": "One short sentence saying what to fix." } ],
  "exclude_item_ids": ["8447139315866"] }
```
`exclude_item_ids` are honoured only if they are in the specialist output and the specialist is `recommendation` or `product_finalization`. `fulfils: true` always wins (issues and ids are ignored). After exclusions, finalization ranks are renumbered; when no product is left the specialist output gets warning `no_suitable_products` and the tray is `[]`. Settings: `REVIEWER_ENABLED` (default true), `REVIEWER_TIMEOUT_SECONDS` (default 15); `REQUEST_TIMEOUT_SECONDS` default is 90.

## Embedding record (single `embeddings` table)
`source_type` (`product|blog|support`), `source_id`, `content`, `metadata` (jsonb), `embedding` vector(1024).
