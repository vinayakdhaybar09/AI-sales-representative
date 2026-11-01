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
        "rank": null, "description": null, "key_benefits": [], "how_to_use": [], "selection_reasons": [] }
    ],
    "suggested_prompts": []
  },
  "error": null
}
```
- `type` ∈ `recommendation | product_finalization | comparison | knowledge | support | clarification | out_of_scope | fallback`.
- `availability` ∈ `in_stock | out_of_stock` (a deliberate addition to the original design doc).
- `rating`, `review_count`, `original_price` on tray cards are optional (null): rating/review_count are null when the product has no reviews (never 0.0); `original_price` is set only when higher than `price`. All come from the `products` table.
- `product_tray` is non-empty only for `recommendation` (up to 5 cards) and `product_finalization` (1–3 cards). Every other response type: `[]`.
- **Featured cards** (`type: "product_finalization"` only; always `null` / `[]` on `recommendation` cards): `rank` (1 = top pick, 2, 3), `description` (markup stripped, max ~500 chars), `key_benefits` (≤5 short strings: the product's benefits, or its features when it lists no benefits), `how_to_use` (≤6 short steps), `selection_reasons` (short factual strings saying why it was picked). Any of them can be empty (some products have no benefits or usage text); the frontend hides empty sections.
- **Featured layout** (frontend decides from the number of cards, ordered by `rank`): 1 card → one large card (image left; name, price, description, key benefits, how to use right). 2 cards → one row, rank 1 at 60% width and rank 2 at 40%. 3 cards → rank 1 as a large card on top, then a row with rank 2 at 60% and rank 3 at 40%.
- Failure: `{"success": false, "conversation_id": "...", "response": null, "error": {"code": "...", "message": "..."}}` for every `/api/*` failure, including 422 (`conversation_id` is `""` if the body had none). HTTP status follows the code: `invalid_request` 422, `rate_limited` 429, `internal_error` 500, `upstream_unavailable` 503, `service_unavailable` 503, `upstream_timeout` 504. Messages are client-safe (no traces, keys or internals).
- `GET /health` → `{"status":"ok","service":"bsc-backend"}`.

Fallback response body:
```json
{ "type": "fallback",
  "markdown": "I’m unable to verify the exact details right now. Please try again or ask about a specific product or category.",
  "product_tray": [],
  "suggested_prompts": ["Suggest a trimmer for body grooming", "Compare two trimmers"] }
```

## Query Understanding output (`app/schemas/query.py`)
```json
{ "intent": "recommendation|product_finalization|comparison|knowledge|support",
  "scope": "in_scope|out_of_scope",
  "entities": {},  "filters": {},  "context": {} }
```
- `entities`: products, category, use_case, body_area, attributes. `filters`: budget_max/min, skin_type, hair_type, gender, required features, exclusions, `result_limit`. `context`: carried-over info, e.g. `previously_mentioned_product_ids`.
- `product_finalization` = the user wants to narrow products already shown down to the best one or two ("narrow it down to your best option", "which one should I buy?", "just one, under ₹300"). It is chosen only when the message refers to earlier results; a fresh request for products stays `recommendation`, and comparing named products stays `comparison`.
- `filters.result_limit` (int 1–3 or null; used only by `product_finalization`): "best one" / "final pick" → 1, "top two" → 2, "shortlist" / "narrow it down to a few" → 3. Null means 1. Anything above 3 is capped at 3.
- `filters.priority` (`"lowest_price" | "highest_rated"` or null; used only by `product_finalization`): set when the user names what matters most ("cheapest one", "best rated"). Other criteria the user states ("under ₹300", "for sensitive skin", "lightweight") go into the existing `filters` / `entities` fields.
- Empty fields are fine. It extracts; it does **not** answer or judge sufficiency. It resolves references like "this product" using conversation state. Exact product matching happens in retrieval.
- `entities`, `filters`, `context` are typed Pydantic sub-models with all fields optional (an empty `{}` is still valid). `context.previously_mentioned_product_ids` is filled by Python from conversation state, never by the LLM. `context.answers_pending_clarification` (bool, default false) is set by the LLM only when the message answers the open clarification question.
- `out_of_scope` is a `scope` value, not a fifth intent.
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
- comparison: `{products: [full rows], comparable_fields: [...], unresolved: [names]}`; ambiguous or fuzzy name matches add warnings.
- knowledge: `{chunks: [{source_id,title,heading,category,url,content,score}], products: [full rows for named products]}`.
- support: `{items: [{source_id,kind,category,content,score}], contact_info: {tracking_url, care_email}, live_order_data_available: false}`.
Warnings used so far: `trimmer_model_not_identified`, `shipping_charges_differ_between_sources`, `returns_wording_differs_between_sources`, `ambiguous_product_name`, `fuzzy_match`, `category_not_matched`, `no_products_within_budget`, `includes_out_of_stock`, `selected_out_of_stock`, `no_products_match_criteria`, `fewer_results_than_requested`, `widened_search`, `no_relevant_*`, `could_not_resolve_two_products`, `specialist_failed`.

## Composer output (internal)
```json
{ "type": "recommendation", "markdown": "...", "product_tray": [],
  "metadata": { "specialists_used": [], "sources": [] } }
```
The envelope's `response` = `type, markdown, product_tray, suggested_prompts` (metadata stays internal).

## Embedding record (single `embeddings` table)
`source_type` (`product|blog|support`), `source_id`, `content`, `metadata` (jsonb), `embedding` vector(1024).
