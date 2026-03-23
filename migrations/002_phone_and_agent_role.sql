-- Migration 002 : ajout phone dans conversation_history + agent_role dans users
ALTER TABLE conversation_history
ADD COLUMN IF NOT EXISTS phone VARCHAR(20);

CREATE INDEX IF NOT EXISTS idx_conv_phone
ON conversation_history(phone);

ALTER TABLE users
ADD COLUMN IF NOT EXISTS agent_role VARCHAR(30) DEFAULT NULL;
