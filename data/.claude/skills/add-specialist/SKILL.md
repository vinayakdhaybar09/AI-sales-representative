---
name: add-specialist
description: Implement or change a BSC specialist (recommendation, comparison, knowledge, support). Use when working in app/specialists/, retrieval, or repositories for a specific intent.
---

# Implement a specialist

1. Read `docs/DATA.md` (retrieval rules, known issues) and `docs/CONTRACTS.md` (specialist output).
2. A specialist retrieves and prepares data. It never writes final prose and never calls the Composer.
3. Return exactly `{specialist, status, data, sources, warnings}` using the Pydantic model in `app/schemas/specialist.py`.
4. Data access: SQL only through `app/db/repositories/*`; vector search only through `app/retrieval/*`, always filtered by `source_type`.
5. Recommendation: semantic search over product embeddings -> candidate IDs -> SQL lookup in `products` -> filters -> rank -> full records. Price, availability, URL, image come only from `products`. Never drop out-of-stock products.
6. Comparison: direct SQL lookup first; embeddings only for fuzzy name resolution; return comparable fields from `products`.
7. Knowledge: `source_type='blog'` chunks, plus product data via SQL when a product is named. Include blog title/heading/URL in `sources`.
8. Support: `source_type='support'`. No order-specific claims. Include tracking link and care email from retrieved data. Apply the trimmer-ambiguity rule (return all variants plus warning `trimmer_model_not_identified`; never pick one).
9. Verify with a small script in `scripts/` that prints the specialist output for 3 to 5 sample queries, including an out-of-stock case and an empty-result case (`status="empty"`).
