-- ============================================================
-- Migration 001 : Gestion multi-utilisateurs + historique
-- BNM Chatbot — 2026-03-15
-- ============================================================

-- Extension UUID (si pas déjà présente)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Table users ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(50)  UNIQUE NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT         NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'client',
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
    last_login    TIMESTAMP
);

-- ── Table conversation_history ───────────────────────────────
CREATE TABLE IF NOT EXISTS conversation_history (
    id         BIGSERIAL    PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    user_id    UUID         REFERENCES users(user_id)
                            ON DELETE SET NULL,
    role       VARCHAR(20)  NOT NULL,
    content    TEXT         NOT NULL,
    intent     VARCHAR(30),
    timestamp  TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- ── Index pour performances ──────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_conv_session
    ON conversation_history(session_id);

CREATE INDEX IF NOT EXISTS idx_conv_user
    ON conversation_history(user_id);

CREATE INDEX IF NOT EXISTS idx_conv_timestamp
    ON conversation_history(timestamp DESC);

-- ── Vérification ─────────────────────────────────────────────
SELECT 'users' AS table_name, COUNT(*) AS rows FROM users
UNION ALL
SELECT 'conversation_history', COUNT(*) FROM conversation_history;
