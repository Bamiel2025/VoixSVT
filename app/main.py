"""API FastAPI et serveur web local du Correcteur audio SVT."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Cookie, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.analysis import AnalysisStore, interpret_laya, utc_now
from app.catalog import catalog_summary, get_question, load_catalog
from app.grader import grade_answer
from app.laya_client import LayaClient, LayaError
from app.settings import (
    ALLOWED_AUDIO_SUFFIXES,
    GOOGLE_SHEETS_APP_URL,
    GOOGLE_SHEETS_TIMEOUT,
    HOSTED_MODE,
    LAYA_MODEL,
    LAYA_PYTHON,
    LAYA_WORKER,
    MAX_AUDIO_SECONDS,
    MAX_UPLOAD_BYTES,
    STATIC_DIR,
    UPLOAD_DIR,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL,
)
from app.sheets_client import GoogleSheetsClient
from app.transcription import TranscriptionError, WhisperService

store = AnalysisStore()
laya = LayaClient(LAYA_PYTHON, LAYA_WORKER, LAYA_MODEL)
whisper = WhisperService(WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE, MAX_AUDIO_SECONDS)
sheets = GoogleSheetsClient(GOOGLE_SHEETS_APP_URL, GOOGLE_SHEETS_TIMEOUT)
laya_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="laya-analysis")
sheets_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="google-sheets")



def _run_sheets_job(analysis_id: str) -> None:
    current = store.get(analysis_id)
    if not current:
        return
    try:
        result = sheets.send_analysis(current)
    except Exception as exc:  # noqa: BLE001 — l'export ne doit pas bloquer l'analyse.
        result = {"status": "error", "label": "Erreur d'export", "message": f"{type(exc).__name__}: {exc}"}
    store.update_sheets(analysis_id, result)


def _run_laya_job(analysis_id: str, question: dict[str, Any], transcription: str) -> None:
    try:
        raw = laya.predict(question, transcription)
        current = store.get(analysis_id)
        if current:
            store.update_laya(analysis_id, interpret_laya(raw, current["deterministic"]))
    except LayaError as exc:
        store.update_laya(
            analysis_id,
            {
                "status": "unavailable",
                "decision_label": "Analyse Laya indisponible",
                "summary": str(exc),
                "metrics": {},
                "agreement": "indisponible",
                "review_required": True,
                "authoritative": False,
                "completed_at": utc_now(),
            },
        )
    except Exception as exc:  # noqa: BLE001 — le job ne doit jamais tuer le serveur web.
        store.update_laya(
            analysis_id,
            {
                "status": "error",
                "decision_label": "Erreur d’analyse Laya",
                "summary": f"{type(exc).__name__}: {exc}",
                "metrics": {},
                "agreement": "indisponible",
                "review_required": True,
                "authoritative": False,
                "completed_at": utc_now(),
            },
        )
    finally:
        current = store.get(analysis_id)
        if current and sheets.configured:
            sheets_executor.submit(_run_sheets_job, analysis_id)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not HOSTED_MODE:
        try:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Système de fichiers en lecture seule (hébergement) : le stockage
            # d'audio local n'est pas utilisable, le démarrage doit continuer.
            pass
    try:
        yield
    finally:
        if not HOSTED_MODE:
            laya_executor.shutdown(wait=False, cancel_futures=True)
            sheets_executor.shutdown(wait=False, cancel_futures=True)
            laya.shutdown()


app = FastAPI(
    title="Correcteur audio SVT",
    version="0.1.0",
    description="Correction locale de réponses orales SVT, cycles 3 et 4",
    lifespan=lifespan,
)
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def privacy_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'"
    )
    return response


class TeacherLoginRequest(BaseModel):
    access_code: str = Field(min_length=1, max_length=160)

    @field_validator("access_code")
    @classmethod
    def reject_blank_code(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Le code est obligatoire")
        return cleaned


class ReferenceRequest(BaseModel):
    access_code: str | None = Field(default=None, max_length=160)

    @field_validator("access_code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AnalysisRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    transcription: str = Field(min_length=1, max_length=1200)
    use_laya: bool = True
    student_first_name: str = Field(min_length=1, max_length=80)
    student_last_name: str = Field(min_length=1, max_length=80)
    student_class: str = Field(min_length=1, max_length=40)

    @field_validator(
        "transcription",
        "student_first_name",
        "student_last_name",
        "student_class",
    )
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Ce champ ne peut pas être vide")
        return cleaned


PUBLIC_QUESTION_FIELDS = (
    "id",
    "level",
    "school_level",
    "theme",
    "bo_theme",
    "title",
    "prompt",
    "context",
)


def _question_public(question: dict[str, Any]) -> dict[str, Any]:
    return {field: question[field] for field in PUBLIC_QUESTION_FIELDS if field in question}


def _teacher_authenticated(session: str | None) -> bool:
    return bool(session and sheets.verify_teacher_token(session))


def _require_teacher(session: str | None) -> None:
    if not _teacher_authenticated(session):
        raise HTTPException(status_code=401, detail="Session enseignant expirée. Saisissez à nouveau le code.")


@app.get("/api/teacher/session")
def teacher_session(voix_teacher: Annotated[str | None, Cookie()] = None) -> dict[str, Any]:
    return {"authenticated": _teacher_authenticated(voix_teacher)}


@app.post("/api/teacher/login")
def teacher_login(payload: TeacherLoginRequest) -> JSONResponse:
    if not os.environ.get("TEACHER_ACCESS_CODE"):
        raise HTTPException(status_code=503, detail="L'espace enseignant n'est pas configuré sur ce serveur.")
    if not sheets.authenticate_teacher(payload.access_code):
        raise HTTPException(status_code=401, detail="Code incorrect.")
    try:
        token = sheets.make_teacher_token()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        "voix_teacher",
        token,
        max_age=8 * 60 * 60,
        httponly=True,
        secure=os.environ.get("COOKIE_SECURE", "1" if os.environ.get("VERCEL") else "0") not in {"0", "false", "False"},
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/teacher/logout")
def teacher_logout() -> JSONResponse:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(
        "voix_teacher",
        path="/",
        secure=os.environ.get("COOKIE_SECURE", "1" if os.environ.get("VERCEL") else "0") not in {"0", "false", "False"},
        httponly=True,
        samesite="strict",
    )
    return response


@app.post("/api/teacher/import")
def teacher_import(voix_teacher: Annotated[str | None, Cookie()] = None) -> dict[str, Any]:
    _require_teacher(voix_teacher)
    result = sheets.fetch_results()
    if not result.get("ok"):
        status = 503 if result.get("status") == "not_configured" else 502
        raise HTTPException(status_code=status, detail=str(result.get("error", "Import impossible.")))
    return result


@app.post("/api/teacher/analyses/clear")
def teacher_clear_analyses(voix_teacher: Annotated[str | None, Cookie()] = None) -> dict[str, Any]:
    _require_teacher(voix_teacher)
    deleted = store.clear()
    return {"ok": True, "deleted": deleted}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "hosted": HOSTED_MODE,
        "audio_processing_local": not HOSTED_MODE,
        "teacher_access_configured": bool(os.environ.get("TEACHER_ACCESS_CODE")),
        "results_export_configured": sheets.configured,
        "questions": len(load_catalog()),
        "catalog": catalog_summary(),
        "whisper": whisper.status(),
        "laya": laya.status(),
        "sheets": sheets.status(),
    }


@app.get("/api/questions")
def questions() -> dict[str, Any]:
    items = [_question_public(item) for item in load_catalog()]
    return {"count": len(items), "questions": items, **catalog_summary()}


@app.get("/api/questions/{question_id}")
def question_detail(question_id: str) -> dict[str, Any]:
    question = get_question(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question introuvable")
    return _question_public(question)


@app.post("/api/questions/{question_id}/reference")
def question_reference(
    question_id: str,
    payload: ReferenceRequest,
    voix_teacher: Annotated[str | None, Cookie()] = None,
) -> dict[str, Any]:
    authorized = _teacher_authenticated(voix_teacher)
    if not authorized and payload.access_code:
        authorized = sheets.authenticate_teacher(payload.access_code)
    if not authorized:
        raise HTTPException(
            status_code=401,
            detail="La réponse de référence est réservée au professeur.",
        )
    question = get_question(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question introuvable")
    return {"id": question_id, "expected_answer": question["expected_answer"]}


@app.post("/api/transcribe")
async def transcribe(file: Annotated[UploadFile, File(...)]) -> JSONResponse:
    if HOSTED_MODE:
        raise HTTPException(status_code=503, detail="La transcription locale n’est pas disponible sur l’hébergement. Utilisez la dictée du navigateur ou saisissez la transcription.")
    original_name = file.filename or "reponse.webm"
    suffix = Path(original_name).suffix.lower()
    content_type = (file.content_type or "").lower()
    if suffix not in ALLOWED_AUDIO_SUFFIXES and not content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Format audio non pris en charge")
    if not content_type.startswith("audio/") and content_type not in {"application/octet-stream", ""}:
        raise HTTPException(status_code=415, detail="Le fichier doit être un audio")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix or '.webm'}"
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Audio trop volumineux (20 Mio maximum)")
                output.write(chunk)
        try:
            result = await run_in_threadpool(whisper.transcribe, target)
        except TranscriptionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(result)
    finally:
        target.unlink(missing_ok=True)
        await file.close()


@app.post("/api/analyze")
async def analyze(payload: AnalysisRequest) -> dict[str, Any]:
    question = get_question(payload.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question introuvable")
    transcription = " ".join(payload.transcription.split())
    deterministic = grade_answer(question, transcription)
    analysis_id = uuid.uuid4().hex
    laya_state: dict[str, Any]
    if payload.use_laya and laya.available and not HOSTED_MODE:
        laya_state = {"status": "queued", "authoritative": False}
    elif payload.use_laya:
        laya_state = {
            "status": "unavailable",
            "decision_label": "Laya non configuré",
            "summary": "Le runtime Laya local est introuvable ou n’est pas activé sur l’hébergement. La grille rapide reste disponible.",
            "metrics": {},
            "review_required": True,
            "authoritative": False,
        }
    else:
        laya_state = {
            "status": "disabled",
            "decision_label": "Analyse Laya désactivée",
            "summary": "Seule la grille déterministe a été utilisée.",
            "metrics": {},
            "review_required": True,
            "authoritative": False,
        }

    sheets_state = {
        "status": "queued" if sheets.configured else "not_configured",
        "label": "Export en attente" if sheets.configured else "Export non configuré",
    }
    if not sheets.configured:
        sheets_state["message"] = "Renseignez GOOGLE_SHEETS_APP_URL pour activer l'envoi."
    analysis = {
        "id": analysis_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "student": {
            "first_name": payload.student_first_name.strip(),
            "last_name": payload.student_last_name.strip(),
            "class_name": payload.student_class.strip(),
        },
        "question": question,
        "transcription": transcription,
        "deterministic": deterministic,
        "laya": laya_state,
        "sheets": sheets_state,
        "teacher_review_required": deterministic["statistics"]["too_long"]
        or deterministic["contradictory"]
        or deterministic["level"] < 2,
    }
    store.create(analysis)
    if payload.use_laya and laya.available and not HOSTED_MODE:
        laya_executor.submit(_run_laya_job, analysis_id, question, transcription)
    elif sheets.configured:
        if HOSTED_MODE:
            _run_sheets_job(analysis_id)
            return store.get(analysis_id) or analysis
        sheets_executor.submit(_run_sheets_job, analysis_id)
    return analysis


@app.get("/api/analysis/{analysis_id}")
def analysis_status(analysis_id: str) -> dict[str, Any]:
    analysis = store.get(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse introuvable ou session expirée")
    return analysis


@app.exception_handler(404)
async def not_found(_, __) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Ressource introuvable"})


def run() -> None:
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
