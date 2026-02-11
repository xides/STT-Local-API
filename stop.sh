#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PORT="${PORT:-8000}"
PID_FILE=".uvicorn.pid"
stopped=0

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}" 2>/dev/null || true
    sleep 1
    if kill -0 "${PID}" 2>/dev/null; then
      kill -9 "${PID}" 2>/dev/null || true
    fi
    stopped=1
    echo "Servicio detenido (PID ${PID})."
  fi
  rm -f "$PID_FILE"
fi

PORT_PIDS="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "${PORT_PIDS}" ]]; then
  kill ${PORT_PIDS} 2>/dev/null || true
  sleep 1
  PORT_PIDS_LEFT="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${PORT_PIDS_LEFT}" ]]; then
    kill -9 ${PORT_PIDS_LEFT} 2>/dev/null || true
  fi
  stopped=1
  echo "Se cerraron procesos escuchando en puerto ${PORT}."
fi

if [[ "${stopped}" -eq 0 ]]; then
  echo "No habia servicios corriendo para detener."
fi
