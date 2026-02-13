# STT Local API (FastAPI + faster-whisper)

Servicio de transcripcion de audio a texto ejecutado localmente con `FastAPI`, `faster-whisper` y `ffmpeg`.

## Caracteristicas

- Endpoint de transcripcion: `POST /transcribe`
- UI de prueba en navegador: `GET /test` (raiz `/` redirige a `/test`)
- Carga de modelo en background al iniciar
- Normalizacion de audio a WAV 16 kHz mono con `ffmpeg`
- Limite de concurrencia configurable para transcripciones
- Restriccion de seguridad configurable para `POST` por host de cliente

## Estructura del proyecto

- `main.py`: API, validaciones, conversion de audio y transcripcion
- `templates/test.html`: interfaz para subir/grabar audio y probar la API
- `start.sh`: levanta `uvicorn` en background y guarda PID en `.uvicorn.pid`
- `stop.sh`: detiene el servicio por PID o por puerto
- `setup_rocky10.sh`: instala dependencias de sistema para Rocky Linux 10.x
- `MODEL_SETUP.md`: guia para preparar un modelo local de `ctranslate2`
- `Dockerfile`: imagen basada en Rocky Linux 10

## Requisitos (ejecucion local)

- Python 3.10+
- `ffmpeg` instalado en el sistema
- Dependencias de `requirements.txt`

## Instalacion en Rocky Linux 10.1

```bash
./setup_rocky10.sh
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Instalacion

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Ejecutar el servicio

### Opcion 1: scripts del proyecto

```bash
./start.sh
```

Detener:

```bash
./stop.sh
```

### Opcion 2: uvicorn directo

```bash
./.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## Endpoints

- `GET /`: redirige a `/test`
- `GET /test`: UI para pruebas manuales (subida de archivo o grabacion)
- `POST /transcribe`: recibe `multipart/form-data` con campo `file`
- `GET /transcribe/logs?limit=10`: devuelve logs recientes de transcripcion

Formatos permitidos por extension: `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.aac`, `.webm`

Ejemplo con `curl`:

```bash
curl -X POST "http://127.0.0.1:8000/transcribe" \
  -F "file=@./audio-test.mp3" \
  -H "Accept: application/json"
```

Respuesta esperada:

```json
{
  "text": "Texto transcrito...",
  "language": "es",
  "segments": [
    { "start": 0.0, "end": 1.2, "text": "Hola" }
  ]
}
```

## Variables de entorno

- `MODEL_NAME` (default: `small`)
- `MODEL_DEVICE` (default: `cpu`)
- `BEAM_SIZE` (default: `5`)
- `MAX_UPLOAD_BYTES` (default: `26214400`, 25 MB)
- `MAX_CONCURRENT_TRANSCRIBES` (default: `1`)
- `FFMPEG_TIMEOUT_SECONDS` (default: `45`)
- `ENABLE_SQLITE_LOGS` (default: `true`)
- `TRANSCRIBE_LOG_DB_PATH` (default: `transcribe_logs.db`)
- `MAX_LOG_PAYLOAD_CHARS` (default: `20000`)
- `ALLOWED_POST_HOSTS` (default: `127.0.0.1,::1`; usa `*` para permitir todos)
- `HOST` (solo para `start.sh`, default: `127.0.0.1`)
- `PORT` (para `start.sh` y `stop.sh`, default: `8000`)

Ejemplo:

```bash
MODEL_NAME=small MODEL_DEVICE=cpu BEAM_SIZE=5 ./start.sh
```

En servidor (red interna o reverse proxy), puedes abrir el endpoint:

```bash
ALLOWED_POST_HOSTS="*" HOST=0.0.0.0 PORT=8000 ./start.sh
```

## Logs de /transcribe en base de datos

Cada request a `POST /transcribe` (exito o error) se guarda en SQLite en:

- `transcribe_logs.db` (por defecto)
- Puedes desactivar esta funcionalidad con `ENABLE_SQLITE_LOGS=false`

Campos registrados: timestamp UTC, host cliente, user-agent, nombre y tipo de archivo, tamano recibido, status HTTP, latencia, payload de respuesta (JSON) y detalle de error.

Consultar ultimos registros:

```bash
sqlite3 transcribe_logs.db "SELECT id, created_at, client_host, filename, status_code, latency_ms FROM transcribe_logs ORDER BY id DESC LIMIT 20;"
```

Ver errores recientes:

```bash
sqlite3 transcribe_logs.db "SELECT id, created_at, status_code, error_detail FROM transcribe_logs WHERE ok = 0 ORDER BY id DESC LIMIT 20;"
```

## Docker

Construir:

```bash
docker build -t local-whisper-stt:latest .
```

Ejecutar:

```bash
docker run --rm -p 8000:8000 --name stt local-whisper-stt:latest
```

Si deseas usar un modelo local ya convertido:

```bash
docker run --rm -p 8000:8000 \
  -v /opt/models/whisper-small:/models/whisper-small \
  -e MODEL_NAME=/models/whisper-small \
  local-whisper-stt:latest
```

Tambien puedes montar cache de Hugging Face:

```bash
docker run --rm -p 8000:8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  local-whisper-stt:latest
```

## Notas de modelo

- El primer arranque puede descargar el modelo si no existe en cache.
- Para un entorno sin internet, prepara/monta un modelo local.
- Consulta `MODEL_SETUP.md` para conversion de `openai/whisper-small` a formato `ctranslate2`.

## Troubleshooting rapido

- `503 Modelo no cargado`: verifica `MODEL_NAME` y que el modelo exista.
- `422 No se pudo procesar el audio`: revisa formato de entrada y `ffmpeg`.
- `413 Archivo demasiado grande`: incrementa `MAX_UPLOAD_BYTES`.
- `429 Servicio ocupado`: incrementa `MAX_CONCURRENT_TRANSCRIBES` o reintenta.
