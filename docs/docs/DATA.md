# DATA

## Datasets (files live in `data/`)
| File | Goes to | Used by | Source of truth for |
|---|---|---|---|
| `bombay-shaving-product-data.json` (~205 products) | `products` table | Recommendation, Comparison, tray cards | price, availability, URL, image, details |
| `bombay-shaving-enriched-products-data-for-embeddings.json` (same IDs) | `embeddings` (`source_type='product'`) | Recommendation (semantic search) | nothing factual; only discovers candidate IDs |
| `bsc-blogs-for-embeddings.json` | `embeddings` (`source_type='blog'`) | Knowledge | grooming/usage knowledge |
| `bsc-support-for-embeddings.json` | `embeddings` (`source_type='support'`) | Support | FAQs, policies, contact info |

The files in the repo may be small samples of the real data. Never hardcode category names, product names, or counts; read them from the data.

## Tables (built in Phase 4 / 5)
**`products`**: `id text PK` (Shopify product id), `category text`, `name text`, `url text`, `image_url text`, `description text`, `price numeric`, `original_price numeric`, `rating numeric`, `review_count int`, `availability text` (`in_stock|out_of_stock`), `details jsonb` (features, detailed_information, specifications, images, discount_percentage, etc.).
- Map from JSON: `availability.status` → `availability`; walk `categories[].products[]`; keep the category from the product's own `category` field.
- Ingestion must be **idempotent** (upsert by `id`).

**`embeddings`**: `id bigserial PK`, `source_type text`, `source_id text`, `content text`, `metadata jsonb`, `embedding vector(1024)`. Unique on `(source_type, source_id)`. Add an HNSW or IVFFlat cosine index only if needed (data is small; exact search is fine for MVP).

Enable once: `CREATE EXTENSION IF NOT EXISTS vector;` Dimension 1024 must match `mistral-embed`; changing the embedding model means re-embedding everything.

## What gets embedded
- **Product**: name + category + product_type + gender_target + short_benefit_summary + searchable_text. `source_id` = `product_id`. Metadata: category, product_type, gender_target, skin_type, concerns, tags, key_ingredients.
- **Blog chunk**: title + category + heading + content. `source_id` = `{blog_id}:{chunk_index}`. Metadata: blog_id, title, category, heading, url (URL is metadata only, not embedded).
- **Support**: FAQ → question + answer + category, `source_id` = `faq:{index}`. Policy → topic + content, `source_id` = `policy:{index}`. Metadata: kind (`faq|policy`), category/topic.
Embed in batches (Mistral free tier is rate limited); make the ingestion script resumable/idempotent.

## Retrieval rules
- Recommendation: embed query → top-k over `source_type='product'` → candidate IDs → SQL lookup in `products` → filter → rank → full records.
- Comparison / product info: direct SQL lookup first; embeddings only to resolve fuzzy names.
- Knowledge: filter `source_type='blog'`. Support: filter `source_type='support'`.
- Always filter by `source_type` in the query; never mix sources in one search.
- Out-of-stock products stay in results.

## Known data issues (do NOT fix; surface via `warnings` or in the Composer where relevant)
1. **Trimmer FAQs are not tied to a trimmer model.** The same question ("What's the run time?", "Is it waterproof?", "Can I use it for beard and body?", "How many combs?", "What charging port?") appears several times with *different* answers (e.g. run time 90 / 120 / 300 minutes; IPX5 / IPX6 / IPX7; steel vs ceramic blades; beard-only vs body-only vs both). Rule: if the user has not identified which trimmer, the Support Specialist must not state a single trimmer-specific fact. Return all matching answers with a warning `trimmer_model_not_identified`, and the Composer asks which model or presents the variants explicitly. Do not "average" or pick one.
2. **Shipping charges conflict**: policy says ₹199 below ₹10 order value and ₹99 below ₹399; FAQ says ₹99 below ₹299 (and ₹80 non-refundable COD fee). State what the retrieved item says and attribute it; do not reconcile. Deferred.
3. **Returns wording**: policies say no returns/exchanges but replacements in eligible cases (48 hours, unboxing video, email), while the FAQ says to raise a request via the Returns page within 2 working days. Report both as written.
4. **Blog chunk headings often do not match their content** (headings look misaligned with the text). Embed as-is; do not rely on heading text for anything beyond display/metadata.
5. **Blog and support items have no IDs**; generate them as specified above.
6. **Category names differ between files** (e.g. canonical `Body Razor & Blades` vs enriched `Razors & Blades`, `Skin Care`, `Fragrance`). Never join or filter on category across the two files; join only on product ID. Treat the canonical table's category as authoritative for display.
7. Some products have `rating: 0.0, review_count: 0` (no reviews). Do not present 0.0 as a real rating; treat as "no ratings yet".
8. Some product descriptions contain stray HTML/CSS comments or emoji (e.g. `<!-- td {...} -->`). Strip nothing in the DB; the Composer should not copy raw markup into prose.
9. `scraped_at` is a snapshot timestamp. Availability may be stale; the data is a snapshot of the product source.
