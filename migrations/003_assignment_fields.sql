-- Migration 003 : vérification champs d'affectation
SELECT username, agent_role FROM users WHERE agent_role IS NOT NULL;
