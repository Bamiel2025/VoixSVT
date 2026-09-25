"""Configuration locale et chemins vers le runtime Laya existant."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "app" / "static"
UPLOAD_DIR = ROOT / "app" / "data" / "uploads"

# L'exposition des variables système Vercel est facultative sur un projet :
# on croise plusieurs indices d'exécution hébergée pour ne jamais considérer
# un serveur serverless comme une session locale.
HOSTED_ENV_SIGNALS = (
    "HOSTED_MODE",
    "VERCEL",
    "VERCEL_ENV",
    "__VC_HANDLER_MODULE_NAME",
    "AWS_LAMBDA_FUNCTION_NAME",
    "LAMBDA_TASK_ROOT",
)
DISABLED_VALUES = {"", "0", "false", "no", "off"}


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() not in DISABLED_VALUES


def detect_hosted_mode(env: Mapping[str, str] | None = None, root: Path | None = None) -> bool:
    """Détecte un runtime hébergé : variables explicites, puis FS en lecture seule."""
    source = os.environ if env is None else env
    if any(_enabled(source.get(name)) for name in HOSTED_ENV_SIGNALS):
        return True
    base = ROOT if root is None else root
    return not os.access(base, os.W_OK)


HOSTED_MODE = detect_hosted_mode()


def env_value(name: str, default: str) -> str:
    """Variable d'environnement : une valeur vide vaut « non définie »."""
    value = os.environ.get(name)
    return default if value is None or not value.strip() else value.strip()


def env_float(name: str, default: float) -> float:
    """Nombre d'environnement : toute valeur illisible vaut le défaut."""
    try:
        return float(env_value(name, str(default)))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    """Entier d'environnement : toute valeur illisible vaut le défaut."""
    try:
        return int(env_value(name, str(default)))
    except ValueError:
        return default


LAYA_HOME = Path(env_value("LAYA_HOME", r"D:\IA\laramxl"))
LAYA_PYTHON = Path(
    env_value("LAYA_PYTHON", str(LAYA_HOME / "laya-mlx" / ".venv" / "Scripts" / "python.exe"))
)
LAYA_WORKER = Path(env_value("LAYA_WORKER", str(LAYA_HOME / "mcp-laya" / "worker.py")))
LAYA_MODEL = env_value("LAYA_MODEL", "aac6fef/laya-multilingual-mlx")

WHISPER_MODEL = env_value("WHISPER_MODEL", "small")
WHISPER_DEVICE = env_value("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = env_value("WHISPER_COMPUTE_TYPE", "int8")
MAX_AUDIO_SECONDS = env_float("MAX_AUDIO_SECONDS", 45.0)
MAX_UPLOAD_BYTES = env_int("MAX_UPLOAD_BYTES", 20 * 1024 * 1024)

ALLOWED_AUDIO_SUFFIXES = {".webm", ".ogg", ".oga", ".mp3", ".wav", ".m4a", ".mp4", ".aac", ".flac"}

# URL /exec du déploiement Google Apps Script. La variable reste vide tant que
# l'enseignant n'a pas déployé le fichier apps-script/Code.gs.
GOOGLE_SHEETS_APP_URL = env_value("GOOGLE_SHEETS_APP_URL", "")
GOOGLE_SHEETS_TIMEOUT = env_float("GOOGLE_SHEETS_TIMEOUT", 10.0)
