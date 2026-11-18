-- app/db/schema.sql
-- Run once against your Neon database (or re-run; all statements are idempotent).
-- Usage: psql $DATABASE_URL -f app/db/schema.sql

-- ─── pgvector extension ──────────────────────────────────────────────────────
-- Must be enabled before creating vector columns.
CREATE EXTENSION IF NOT EXISTS vector;

-- ─── products ─────────────────────────────────────────────────────────────────
-- Single source of truth for price, availability, URL, image, and product
-- details. The 'details' jsonb column stores everything that doesn't need its
-- own indexed column: features, detailed_information, specifications, images
-- list, discount_percentage, and the source snapshot metadata.
--
-- 'availability' stores the string directly ('in_stock' | 'out_of_stock');
-- mapped from availability.status in the JSON.
CREATE TABLE IF NOT EXISTS products (
    id               TEXT        PRIMARY KEY,       -- Shopify product id
    category         TEXT        NOT NULL,
    name             TEXT        NOT NULL,
    url              TEXT        NOT NULL,
    image_url        TEXT        NOT NULL DEFAULT '',
    description      TEXT        NOT NULL DEFAULT '',
    price            NUMERIC     NOT NULL DEFAULT 0,
    original_price   NUMERIC     NOT NULL DEFAULT 0,
    rating           NUMERIC     NOT NULL DEFAULT 0,
    review_count     INTEGER     NOT NULL DEFAULT 0,
    availability     TEXT        NOT NULL DEFAULT 'out_of_stock',
    details          JSONB       NOT NULL DEFAULT '{}'
);

-- ─── embeddings ───────────────────────────────────────────────────────────────
-- One row per embeddable chunk (product, blog chunk, support item).
-- 'source_type' ∈ 'product' | 'blog' | 'support'.
-- 'source_id' is unique within a source_type (e.g. Shopify id, faq:0, policy:1).
-- 'embedding' is a 1024-dim vector matching mistral-embed.
CREATE TABLE IF NOT EXISTS embeddings (
    id          BIGSERIAL   PRIMARY KEY,
    source_type TEXT        NOT NULL,
    source_id   TEXT        NOT NULL,
    content     TEXT        NOT NULL,
    metadata    JSONB       NOT NULL DEFAULT '{}',
    embedding   VECTOR(1024),
    UNIQUE (source_type, source_id)
);

-- Index for cosine similarity search on embeddings (added here for reference;
-- exact search is fine for MVP — enable IVFFlat/HNSW later if needed).
-- CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);


-- ─── conversations ────────────────────────────────────────────────────────────
-- One row per guest conversation_id. 'history' keeps the last few messages,
-- 'previous_product_ids' the products shown last, 'pending_clarification' the
-- open clarification (docs/CONTRACTS.md shape) or NULL. Rows idle longer than
-- CONVERSATION_TTL_MINUTES are treated as expired and deleted.
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id       TEXT        PRIMARY KEY,
    history               JSONB       NOT NULL DEFAULT '[]',
    previous_product_ids  JSONB       NOT NULL DEFAULT '[]',
    pending_clarification JSONB,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Product finalization + structured memory (added later; safe to re-run).
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pool_search_text      TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pool_match_scores     JSONB NOT NULL DEFAULT '{}';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS finalized_product_ids JSONB NOT NULL DEFAULT '[]';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS preferences           JSONB NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS conversations_updated_at_idx ON conversations (updated_at);

-- ─── support_queries ──────────────────────────────────────────────────────────
-- Queries raised from the in-chat form (demo). Stored exactly as submitted: no
-- re-validation, no email, no image bytes (only attachment metadata).
-- 'ref' is derived from the id. 'idempotency_key' makes a double click harmless.
CREATE TABLE IF NOT EXISTS support_queries (
    id               BIGSERIAL   PRIMARY KEY,
    ref              TEXT        GENERATED ALWAYS AS ('BSC-Q-' || (id + 1000)::text) STORED,
    conversation_id  TEXT        NOT NULL,
    idempotency_key  TEXT        NOT NULL UNIQUE,
    category         TEXT        NOT NULL DEFAULT '',
    description      TEXT        NOT NULL DEFAULT '',
    details          JSONB       NOT NULL DEFAULT '{}',
    attachments_meta JSONB       NOT NULL DEFAULT '[]',
    status           TEXT        NOT NULL DEFAULT 'submitted',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS support_queries_conversation_idx ON support_queries (conversation_id);

-- ─── salesperson agent (app/agent) ───────────────────────────────────────────
-- One row per chat: compact transcript (user text + assistant text only), the
-- customer profile the agent builds up, and the product ids already shown.
CREATE TABLE IF NOT EXISTS chat_sessions (
    conversation_id TEXT        PRIMARY KEY,
    messages        JSONB       NOT NULL DEFAULT '[]',
    profile         JSONB       NOT NULL DEFAULT '{}',
    shown_ids       JSONB       NOT NULL DEFAULT '[]',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per customer message: what was asked, which tools ran, what was shown,
-- how fast, and whether anything went wrong. Feeds the admin analytics view.
CREATE TABLE IF NOT EXISTS turn_logs (
    id               BIGSERIAL   PRIMARY KEY,
    conversation_id  TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_message     TEXT        NOT NULL,
    reply            TEXT        NOT NULL DEFAULT '',
    intent           TEXT        NOT NULL DEFAULT 'other',
    tools            JSONB       NOT NULL DEFAULT '[]',   -- [{name, args, ms, result_count}]
    products_shown   JSONB       NOT NULL DEFAULT '[]',
    unmet_queries    JSONB       NOT NULL DEFAULT '[]',   -- searches that found nothing useful
    guard_issues     JSONB       NOT NULL DEFAULT '[]',
    handoff          BOOLEAN     NOT NULL DEFAULT false,
    model            TEXT,
    first_token_ms   INTEGER,
    total_ms         INTEGER,
    tokens           INTEGER,
    error            TEXT
);
CREATE INDEX IF NOT EXISTS turn_logs_created_idx ON turn_logs (created_at);
CREATE INDEX IF NOT EXISTS turn_logs_conv_idx ON turn_logs (conversation_id);

-- Clicks, add-to-cart, chips: sent by the frontend (POST /api/events).
CREATE TABLE IF NOT EXISTS chat_events (
    id              BIGSERIAL   PRIMARY KEY,
    conversation_id TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type      TEXT        NOT NULL,   -- product_click | add_to_cart | chip_click | checkout | bundle_add_all | feedback
    product_id      TEXT,
    meta            JSONB       NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS chat_events_created_idx ON chat_events (created_at);
