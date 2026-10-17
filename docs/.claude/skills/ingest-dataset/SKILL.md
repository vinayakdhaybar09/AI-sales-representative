---
name: ingest-dataset
description: Write or modify ingestion scripts that load BSC JSON data into Postgres (products table) or create embeddings (products, blogs, support). Use when working in scripts/ingest_*.py, app/db/schema.sql, or embedding storage.
---

# Ingest a dataset

1. Read `docs/DATA.md` fully (tables, what gets embedded, source_id formats, known issues).
2. Scripts run as `python -m scripts.<name>` from the project root and use `get_settings()`; fail with a clear message if a required key or `DATABASE_URL` is missing.
3. Idempotent: upsert by primary key (`products.id`) or by unique `(source_type, source_id)`. Re-running must not duplicate rows.
4. Do not clean or alter the data (see Known issues). Preserve raw fields in `details` / `metadata` jsonb.
5. Embeddings: batch requests, handle Mistral rate limits with simple backoff, embed text exactly as specified in `docs/DATA.md`, verify vector length equals `embedding_dimensions` (1024) before insert.
6. Check current docs for the DB driver, pgvector adapter, and Mistral embedding API before coding; pin versions.
7. Print a summary at the end (rows inserted/updated/skipped per source_type) so the owner can verify counts.
