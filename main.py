from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Query
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
import sqlite3
import json
from datetime import datetime, timezone

MODEL_NAME = os.getenv("MODEL_NAME", "small")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu")
BEAM_SIZE = int(os.getenv("BEAM_SIZE", "5"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_CONCURRENT_TRANSCRIBES = int(os.getenv("MAX_CONCURRENT_TRANSCRIBES", "1"))
FFMPEG_TIMEOUT_SECONDS = int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "45"))
ENABLE_SQLITE_LOGS = os.getenv("ENABLE_SQLITE_LOGS", "true").strip().lower() in {"1", "true", "yes", "on"}
TRANSCRIBE_LOG_DB_PATH = str(Path(os.getenv("TRANSCRIBE_LOG_DB_PATH", "transcribe_logs.db")).expanduser().resolve())
MAX_LOG_PAYLOAD_CHARS = int(os.getenv("MAX_LOG_PAYLOAD_CHARS", "20000"))
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
db_lock = threading.Lock()
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


def _truncate_for_log(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"


def _init_transcribe_log_db():
    if not ENABLE_SQLITE_LOGS:
        logger.info("SQLite logs desactivados por ENABLE_SQLITE_LOGS=false")
        return
    db_parent = Path(TRANSCRIBE_LOG_DB_PATH).parent
    db_parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(TRANSCRIBE_LOG_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transcribe_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                client_host TEXT,
                user_agent TEXT,
                filename TEXT,
                content_type TEXT,
                file_size_bytes INTEGER,
                status_code INTEGER NOT NULL,
                ok INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                response_json TEXT,
                error_detail TEXT
            )
            """
        )
        conn.commit()


def _log_transcribe_event(
    *,
    client_host: str,
    user_agent: str,
    filename: str,
    content_type: str,
    file_size_bytes: int,
    status_code: int,
    latency_ms: int,
    response_payload: dict,
    error_detail: str,
):
    if not ENABLE_SQLITE_LOGS:
        return
    response_json = ""
    if response_payload is not None:
        response_json = _truncate_for_log(
            json.dumps(response_payload, ensure_ascii=False),
            MAX_LOG_PAYLOAD_CHARS,
        )
    safe_error_detail = _truncate_for_log(error_detail or "", MAX_LOG_PAYLOAD_CHARS)
    try:
        with db_lock:
            with sqlite3.connect(TRANSCRIBE_LOG_DB_PATH) as conn:
                conn.execute(
                    """
                    INSERT INTO transcribe_logs (
                        created_at,
                        client_host,
                        user_agent,
                        filename,
                        content_type,
                        file_size_bytes,
                        status_code,
                        ok,
                        latency_ms,
                        response_json,
                        error_detail
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now(timezone.utc).isoformat(),
                        client_host,
                        user_agent,
                        filename,
                        content_type,
                        file_size_bytes,
                        status_code,
                        1 if 200 <= status_code < 300 else 0,
                        latency_ms,
                        response_json,
                        safe_error_detail,
                    ),
                )
                conn.commit()
    except Exception as e:
        logger.exception("No se pudo guardar log de /transcribe: %s", e)


def _read_recent_transcribe_logs(limit: int) -> list[dict]:
    if not ENABLE_SQLITE_LOGS:
        return []
    safe_limit = max(1, min(limit, 100))
    with db_lock:
        with sqlite3.connect(TRANSCRIBE_LOG_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    client_host,
                    user_agent,
                    filename,
                    content_type,
                    file_size_bytes,
                    status_code,
                    ok,
                    latency_ms,
                    response_json,
                    error_detail
                FROM transcribe_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

    out = []
    for row in rows:
        response_payload = None
        if row["response_json"]:
            try:
                response_payload = json.loads(row["response_json"])
            except json.JSONDecodeError:
                response_payload = row["response_json"]

        out.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "client_host": row["client_host"],
                "user_agent": row["user_agent"],
                "filename": row["filename"],
                "content_type": row["content_type"],
                "file_size_bytes": row["file_size_bytes"],
                "status_code": row["status_code"],
                "ok": bool(row["ok"]),
                "latency_ms": row["latency_ms"],
                "response": response_payload,
                "error_detail": row["error_detail"],
            }
        )
    return out


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
    _init_transcribe_log_db()
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


@app.get("/transcribe/logs")
async def transcribe_logs(limit: int = Query(default=10, ge=1, le=100)):
    try:
        logs = _read_recent_transcribe_logs(limit)
        return {"enabled": ENABLE_SQLITE_LOGS, "count": len(logs), "logs": logs}
    except Exception as e:
        logger.exception("No se pudo leer logs de /transcribe: %s", e)
        raise HTTPException(status_code=500, detail="No se pudieron leer los logs")


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(request: Request, file: UploadFile = File(...)):
    started_at = time.time()
    acquired = False
    status_code = 500
    error_detail = ""
    response_payload = None
    uploaded_bytes = 0
    client_host = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    filename = Path(file.filename or "uploaded").name
    content_type = (file.content_type or "").split(";")[0].strip().lower()

    try:
        acquired = transcribe_semaphore.acquire(blocking=False)
        if not acquired:
            raise HTTPException(status_code=429, detail="Servicio ocupado. Reintente en unos segundos.")

        if not ensure_model_loaded():
            raise HTTPException(status_code=503, detail="Modelo no cargado todavia. Reintente en unos minutos o convierta/instale el modelo requerido.")

        suffix = os.path.splitext(filename)[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail="Formato de audio no soportado")

        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Content-Type no permitido: {content_type}")

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "input" + suffix)
            out_path = os.path.join(tmpdir, "audio.wav")
            uploaded_bytes = await _save_upload_with_limit(file, in_path, MAX_UPLOAD_BYTES)

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

            segments, info = model.transcribe(out_path, beam_size=BEAM_SIZE)

            texts = []
            out_segments = []
            for s in segments:
                texts.append(s.text)
                out_segments.append({"start": float(s.start), "end": float(s.end), "text": s.text})

            full_text = " ".join(texts).strip()
            if hasattr(info, "language"):
                language = info.language
            elif isinstance(info, dict):
                language = info.get("language", "unknown")
            else:
                language = "unknown"

            response_payload = {"text": full_text, "language": language, "segments": out_segments}
            status_code = 200
            return response_payload
    except HTTPException as e:
        status_code = e.status_code
        error_detail = str(e.detail)
        raise
    except Exception as e:
        status_code = 500
        error_detail = f"Error interno no manejado: {type(e).__name__}"
        logger.exception("Error inesperado en /transcribe: %s", e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    finally:
        latency_ms = int((time.time() - started_at) * 1000)
        await file.close()
        if acquired:
            transcribe_semaphore.release()
        _log_transcribe_event(
            client_host=client_host,
            user_agent=user_agent,
            filename=filename,
            content_type=content_type,
            file_size_bytes=uploaded_bytes,
            status_code=status_code,
            latency_ms=latency_ms,
            response_payload=response_payload,
            error_detail=error_detail,
        )
