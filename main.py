from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from faster_whisper import WhisperModel
from pathlib import Path
import threading
import logging
import tempfile
import subprocess
import os
from typing import List
import time

MODEL_NAME = os.getenv("MODEL_NAME", "small")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu")
BEAM_SIZE = int(os.getenv("BEAM_SIZE", "5"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_CONCURRENT_TRANSCRIBES = int(os.getenv("MAX_CONCURRENT_TRANSCRIBES", "1"))
FFMPEG_TIMEOUT_SECONDS = int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "45"))
ALLOWED_POST_HOSTS = {
    h.strip() for h in os.getenv("ALLOWED_POST_HOSTS", "127.0.0.1,::1").split(",") if h.strip()
}
ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".webm"}
ALLOWED_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/flac",
    "audio/ogg",
    "audio/aac",
    "audio/webm",
    "application/octet-stream",
}

app = FastAPI(title="Local Whisper STT", version="0.1")
model = None
model_lock = threading.Lock()
model_loading = False
transcribe_semaphore = threading.BoundedSemaphore(value=max(1, MAX_CONCURRENT_TRANSCRIBES))
logger = logging.getLogger("uvicorn.error")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
TEST_PAGE_PATH = TEMPLATES_DIR / "test.html"


def _load_test_page_html() -> str:
    if not TEST_PAGE_PATH.exists():
        raise RuntimeError(f"No se encontro la plantilla HTML: {TEST_PAGE_PATH}")
    return TEST_PAGE_PATH.read_text(encoding="utf-8")


TEST_PAGE_HTML = _load_test_page_html()

class Segment(BaseModel):
    start: float
    end: float
    text: str

class TranscriptionResponse(BaseModel):
    text: str
    language: str
    segments: List[Segment]


async def _save_upload_with_limit(upload: UploadFile, destination_path: str, max_bytes: int) -> int:
    total_bytes = 0
    chunk_size = 1024 * 1024
    with open(destination_path, "wb") as destination:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Archivo demasiado grande. Maximo permitido: {max_bytes} bytes",
                )
            destination.write(chunk)
    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="Archivo vacio")
    return total_bytes


def _is_allowed_post_host(host: str) -> bool:
    if "*" in ALLOWED_POST_HOSTS:
        return True
    return host in ALLOWED_POST_HOSTS


@app.middleware("http")
async def restrict_post_to_localhost(request: Request, call_next):
    client_host = request.client.host if request.client else ""
    if request.method == "POST" and not _is_allowed_post_host(client_host):
        return JSONResponse(
            status_code=403,
            content={"detail": "Host no permitido para POST. Ajusta ALLOWED_POST_HOSTS para habilitarlo."},
        )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "microphone=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "media-src 'self' blob:; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    return response


def _load_model_sync():
    global model, model_loading
    try:
        logger.info("Cargando modelo %s en dispositivo %s", MODEL_NAME, MODEL_DEVICE)
        m = WhisperModel(MODEL_NAME, device=MODEL_DEVICE)
        with model_lock:
            model = m
        logger.info("Modelo cargado correctamente")
    except Exception as e:
        logger.exception("Error cargando el modelo: %s", e)
    finally:
        model_loading = False

@app.on_event("startup")
def start_model_loader():
    global model_loading
    # Iniciar la carga en background para que la app no falle al arrancar
    if model is None and not model_loading:
        model_loading = True
        t = threading.Thread(target=_load_model_sync, daemon=True)
        t.start()

def ensure_model_loaded():
    """Sincroniza la carga del modelo si no está cargado.
    Intenta esperar un corto periodo para la carga y devuelve True si está listo.
    """
    global model, model_loading
    if model is not None:
        return True
    # Si ya hay un loader en progreso, esperar unos segundos
    waited = 0
    while model is None and model_loading and waited < 15:
        time.sleep(1)
        waited += 1
    return model is not None


@app.get("/test", response_class=HTMLResponse)
async def test_ui():
    return TEST_PAGE_HTML


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/test", status_code=307)


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(file: UploadFile = File(...)):
    acquired = transcribe_semaphore.acquire(blocking=False)
    if not acquired:
        raise HTTPException(status_code=429, detail="Servicio ocupado. Reintente en unos segundos.")

    # Verificar que el modelo esté listo
    try:
        if not ensure_model_loaded():
            raise HTTPException(status_code=503, detail="Modelo no cargado todavia. Reintente en unos minutos o convierta/instale el modelo requerido.")

        filename = Path(file.filename or "uploaded").name
        suffix = os.path.splitext(filename)[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail="Formato de audio no soportado")

        content_type = (file.content_type or "").split(";")[0].strip().lower()
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Content-Type no permitido: {content_type}")

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "input" + suffix)
            out_path = os.path.join(tmpdir, "audio.wav")
            await _save_upload_with_limit(file, in_path, MAX_UPLOAD_BYTES)

            # Normalizar y convertir a WAV 16k mono con ffmpeg
            cmd = [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                in_path,
                "-vn",
                "-sn",
                "-dn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-sample_fmt",
                "s16",
                out_path,
            ]

            try:
                subprocess.run(cmd, check=True, timeout=FFMPEG_TIMEOUT_SECONDS, capture_output=True)
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=504, detail="Tiempo de procesamiento excedido en ffmpeg")
            except subprocess.CalledProcessError:
                raise HTTPException(status_code=422, detail="No se pudo procesar el audio con ffmpeg")

            # Transcribir con faster-whisper
            segments, info = model.transcribe(out_path, beam_size=BEAM_SIZE)

            texts = []
            out_segments = []
            for s in segments:
                texts.append(s.text)
                out_segments.append({"start": float(s.start), "end": float(s.end), "text": s.text})

            full_text = " ".join(texts).strip()
            language = None
            if hasattr(info, "language"):
                language = info.language
            elif isinstance(info, dict):
                language = info.get("language", "unknown")
            else:
                language = "unknown"

            return {"text": full_text, "language": language, "segments": out_segments}
    finally:
        await file.close()
        transcribe_semaphore.release()
