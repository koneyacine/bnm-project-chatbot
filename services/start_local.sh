#!/usr/bin/env bash
# start_local.sh — Démarre tous les microservices en local (sans Docker)
# Usage : bash services/start_local.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON=/opt/anaconda3/bin/python3

echo "========================================"
echo "  BNM Chatbot — Microservices (local)"
echo "========================================"
echo ""

# Tuer les anciens processus
for PORT in 8000 8001 8002 8003 8004 8005; do
  lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
done
sleep 1

# Démarrer chaque service depuis son répertoire
start_service() {
  local name="$1"
  local port="$2"
  local dir="$ROOT/services/$name"
  echo "  → $name (port $port)..."
  cd "$dir"
  BNM_DATA_DIR="$ROOT" $PYTHON -m uvicorn main:app \
    --host 0.0.0.0 --port "$port" \
    > "/tmp/bnm_${name}.log" 2>&1 &
  echo "    PID=$!"
}

start_service "auth-service"     8001
start_service "chat-service"     8002
start_service "ticket-service"   8003
start_service "document-service" 8004
start_service "admin-service"    8005
sleep 3
start_service "gateway"          8000

sleep 8

echo ""
echo "  Vérification des services :"
for s in "auth-service:8001" "chat-service:8002" "ticket-service:8003" \
          "document-service:8004" "admin-service:8005" "gateway:8000"; do
  name="${s%%:*}"
  port="${s##*:}"
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/health" 2>/dev/null || echo "ERR")
  if [ "$code" = "200" ]; then
    echo "    ✓ $name → http://localhost:$port"
  else
    echo "    ✗ $name → ERREUR (code=$code)"
    echo "      logs: tail /tmp/bnm_${name}.log"
  fi
done

echo ""
echo "  Logs : tail -f /tmp/bnm_<service>.log"
echo "========================================"
