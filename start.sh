#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PID_FILE=".uvicorn.pid"
LOG_FILE="uvicorn.log"

if [[ ! -x ".venv/bin/uvicorn" ]]; then
  echo "No se encontro .venv/bin/uvicorn. Activa/crea el virtualenv primero."
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
    echo "Servicio ya corriendo (PID ${OLD_PID})."
    echo "URL: http://${HOST}:${PORT}/"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

nohup ./.venv/bin/uvicorn main:app --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 1
if kill -0 "$NEW_PID" 2>/dev/null; then
  echo "Servicio iniciado (PID $NEW_PID)."
  echo "URL: http://${HOST}:${PORT}/"
  echo "Log: $ROOT_DIR/$LOG_FILE"
else
  echo "Fallo al iniciar servicio. Revisa $LOG_FILE"
  exit 1
fi
