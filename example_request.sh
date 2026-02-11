#!/bin/bash
# Ejemplo de request usando curl
if [ -z "$1" ]; then
  echo "Uso: $0 <audio-file>"
  exit 1
fi

curl -X POST "http://localhost:8000/transcribe" \
  -F "file=@${1}" \
  -H "Accept: application/json"
