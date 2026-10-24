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
        "rating": 4.79, "review_count": 202, "original_price": 149.0 }
    ],
    "suggested_prompts": []
  },
  "error": null
}
```
- `type` ∈ `recommendation | comparison | knowledge | support | clarification | out_of_scope | fallback`.
- `availability` ∈ `in_stock | out_of_stock` (a deliberate addition to the original design doc).
- `rating`, `review_count`, `original_price` on tray cards are optional (null): rating/review_count are null when the product has no reviews (never 0.0); `original_price` is set only when higher than `price`. All come from the `products` table.
- Non-recommendation responses: `product_tray` is `[]`.
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
{ "intent": "recommendation|comparison|knowledge|support",
  "scope": "in_scope|out_of_scope",
  "entities": {},  "filters": {},  "context": {} }
```
- `entities`: products, category, use_case, body_area, attributes. `filters`: budget_max/min, skin_type, hair_type, gender, required features, exclusions. `context`: carried-over info, e.g. `previously_mentioned_product_ids`.
- Empty fields are fine. It extracts; it does **not** answer or judge sufficiency. It resolves references like "this product" using conversation state. Exact product matching happens in retrieval.
- `entities`, `filters`, `context` are typed Pydantic sub-models with all fields optional (an empty `{}` is still valid). `context.previously_mentioned_product_ids` is filled by Python from conversation state, never by the LLM. `context.answers_pending_clarification` (bool, default false) is set by the LLM only when the message answers the open clarification question.
- `out_of_scope` is a `scope` value, not a fifth intent.
- Example: `{"intent":"recommendation","scope":"in_scope","entities":{"category":"trimmer","use_case":["body_grooming"]},"filters":{"budget_max":2000},"context":{"previously_mentioned_product_ids":[]}}`

## Pending clarification (in conversation state)
```json
{ "pending_clarification": { "original_query": "Suggest a trimmer", "intent": "recommendation",
  "missing_field": "use_case",
  "question": "What will you mainly use the trimmer for: beard grooming, body grooming, or both?",
  "attempt_count": 1 } }
```

## Specialist output (`app/schemas/specialist.py`)
```json
{ "specialist": "recommendation|comparison|knowledge|support",
  "status": "success|empty|error",
  "data": {}, "sources": [], "warnings": [] }
```
`data` differs by specialist:
- recommendation: `{products: [full products row + match_score]}` (max 5, similarity order, out-of-stock kept).
- comparison: `{products: [full rows], comparable_fields: [...], unresolved: [names]}`; ambiguous or fuzzy name matches add warnings.
- knowledge: `{chunks: [{source_id,title,heading,category,url,content,score}], products: [full rows for named products]}`.
- support: `{items: [{source_id,kind,category,content,score}], contact_info: {tracking_url, care_email}, live_order_data_available: false}`.
Warnings used so far: `trimmer_model_not_identified`, `shipping_charges_differ_between_sources`, `returns_wording_differs_between_sources`, `ambiguous_product_name`, `fuzzy_match`, `category_not_matched`, `no_products_within_budget`, `includes_out_of_stock`, `no_relevant_*`, `could_not_resolve_two_products`, `specialist_failed`.

## Composer output (internal)
```json
{ "type": "recommendation", "markdown": "...", "product_tray": [],
  "metadata": { "specialists_used": [], "sources": [] } }
```
The envelope's `response` = `type, markdown, product_tray, suggested_prompts` (metadata stays internal).

## Embedding record (single `embeddings` table)
`source_type` (`product|blog|support`), `source_id`, `content`, `metadata` (jsonb), `embedding` vector(1024).
