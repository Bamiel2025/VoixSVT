"""Configuration locale et chemins vers le runtime Laya existant."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "app" / "static"
UPLOAD_DIR = ROOT / "app" / "data" / "uploads"
HOSTED_MODE = os.environ.get("VERCEL", "").lower() in {"1", "true", "yes"} or os.environ.get("HOSTED_MODE", "").lower() in {"1", "true", "yes"}

LAYA_HOME = Path(os.environ.get("LAYA_HOME", r"D:\IA\laramxl"))
LAYA_PYTHON = Path(
    os.environ.get("LAYA_PYTHON", str(LAYA_HOME / "laya-mlx" / ".venv" / "Scripts" / "python.exe"))
)
LAYA_WORKER = Path(
    os.environ.get("LAYA_WORKER", str(LAYA_HOME / "mcp-laya" / "worker.py"))
)
LAYA_MODEL = os.environ.get("LAYA_MODEL", "aac6fef/laya-multilingual-mlx")

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
MAX_AUDIO_SECONDS = float(os.environ.get("MAX_AUDIO_SECONDS", "45"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

ALLOWED_AUDIO_SUFFIXES = {".webm", ".ogg", ".oga", ".mp3", ".wav", ".m4a", ".mp4", ".aac", ".flac"}

# URL /exec du déploiement Google Apps Script. La variable reste vide tant que
# l'enseignant n'a pas déployé le fichier apps-script/Code.gs.
GOOGLE_SHEETS_APP_URL = os.environ.get("GOOGLE_SHEETS_APP_URL", "").strip()
GOOGLE_SHEETS_TIMEOUT = float(os.environ.get("GOOGLE_SHEETS_TIMEOUT", "10"))
