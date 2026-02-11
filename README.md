# STT Local API (FastAPI + faster-whisper)

Servicio de transcripcion de audio a texto ejecutado localmente con `FastAPI`, `faster-whisper` y `ffmpeg`.

## Caracteristicas

- Endpoint de transcripcion: `POST /transcribe`
- UI de prueba en navegador: `GET /test` (raiz `/` redirige a `/test`)
- Carga de modelo en background al iniciar
- Normalizacion de audio a WAV 16 kHz mono con `ffmpeg`
- Limite de concurrencia configurable para transcripciones
- Restriccion de seguridad: los `POST` solo se aceptan desde `127.0.0.1`

## Estructura del proyecto

- `main.py`: API, validaciones, conversion de audio y transcripcion
- `templates/test.html`: interfaz para subir/grabar audio y probar la API
- `start.sh`: levanta `uvicorn` en background y guarda PID en `.uvicorn.pid`
- `stop.sh`: detiene el servicio por PID o por puerto
- `MODEL_SETUP.md`: guia para preparar un modelo local de `ctranslate2`
- `Dockerfile`: imagen basada en Rocky Linux 8

## Requisitos (ejecucion local)

- Python 3.9+
- `ffmpeg` instalado en el sistema
- Dependencias de `requirements.txt`

## Instalacion

```bash
python3.9 -m venv .venv
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
- `HOST` (solo para `start.sh`, default: `127.0.0.1`)
- `PORT` (para `start.sh` y `stop.sh`, default: `8000`)

Ejemplo:

```bash
MODEL_NAME=small MODEL_DEVICE=cpu BEAM_SIZE=5 ./start.sh
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
