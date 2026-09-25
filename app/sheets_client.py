"""Client léger pour l'export des analyses vers Google Apps Script."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import time
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import Request, urlopen


class GoogleSheetsClient:
    """Envoie une analyse à une Web App Google Apps Script.

    L'URL reste facultative : la correction locale fonctionne sans connexion
    externe. Sans URL, l'appel retourne un état explicite pour l'interface.
    """

    def __init__(self, app_url: str = "", timeout: float = 10.0) -> None:
        self.app_url = app_url.strip()
        self.timeout = max(0.5, float(timeout))

    @property
    def configured(self) -> bool:
        return bool(self.app_url)

    def _request_url(self, **extra: str) -> str:
        """URL de la Web App avec la clé d'accès de la Web App.

        La clé est lue dans l'URL (``?key=``) si elle y figure, sinon dans la
        variable d'environnement ``WEB_APP_SECRET``. Elle doit être identique à
        la propriété de script ``WEB_APP_SECRET`` d'Apps Script.
        """
        parsed = urlparse(self.app_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if not query.get("key"):
            secret = os.environ.get("WEB_APP_SECRET", "").strip()
            if secret:
                query["key"] = secret
        query.update(extra)
        return parsed._replace(query=urlencode(query)).geturl()

    def status(self) -> dict[str, Any]:
        return {"configured": self.configured, "label": "Configuré" if self.configured else "Non configuré"}

    def send_analysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Envoie une analyse et retourne un état serialisable."""
        if not self.configured:
            return {"status": "not_configured", "label": "Export non configuré", "message": "Renseignez GOOGLE_SHEETS_APP_URL pour activer l'envoi."}
        request = Request(
            self._request_url(),
            data=json.dumps(self.build_payload(analysis), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                try:
                    response_payload = json.loads(body)
                except json.JSONDecodeError:
                    response_payload = {"message": body.strip()[:300]}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            return {"status": "error", "label": "Erreur Google Sheets", "message": f"HTTP {exc.code}{f' — {detail}' if detail else ''}"}
        except (TimeoutError, URLError, OSError) as exc:
            return {"status": "error", "label": "Google Sheets inaccessible", "message": str(exc)[:300]}
        if isinstance(response_payload, dict) and response_payload.get("ok") is False:
            return {"status": "error", "label": "Erreur Google Sheets", "message": str(response_payload.get("error", "Réponse invalide"))[:300]}
        if not isinstance(response_payload, dict) or response_payload.get("ok") is not True:
            return {
                "status": "error",
                "label": "Réponse Google Sheets invalide",
                "message": "Le script n’a pas confirmé l’enregistrement avec {ok: true}.",
            }
        message = str(response_payload.get("message", "Ligne ajoutée."))[:300]
        return {"status": "sent", "label": "Résultat envoyé", "message": message}

    @staticmethod
    def build_payload(analysis: dict[str, Any]) -> dict[str, Any]:
        """Construit le contrat de données entre Python et Apps Script."""
        student = analysis.get("student") or {}
        question = analysis.get("question") or {}
        deterministic = analysis.get("deterministic") or {}
        laya = analysis.get("laya") or {}
        remediation = deterministic.get("remediation") or {}
        source = question.get("source") or {}
        return {
            "schema": "voix-svt-analysis-v1",
            "analysis_id": analysis.get("id", ""),
            "created_at": analysis.get("created_at", ""),
            "updated_at": analysis.get("updated_at", ""),
            "student": {key: student.get(key, "") for key in ("first_name", "last_name", "class_name")},
            "question": {key: question.get(key, "") for key in ("id", "level", "school_level", "theme", "title", "prompt")},
            "transcription": analysis.get("transcription", ""),
            "result": {
                "score": deterministic.get("level", 0), "max_score": deterministic.get("max_level", 4), "label": deterministic.get("label", ""), "verdict": deterministic.get("verdict", ""), "coverage": deterministic.get("coverage", 0), "complete": bool(deterministic.get("complete", False)), "contradictory": bool(deterministic.get("contradictory", False)), "words": (deterministic.get("statistics") or {}).get("words", 0), "sentences": (deterministic.get("statistics") or {}).get("sentences", 0), "teacher_review_required": bool(analysis.get("teacher_review_required", False)),
            },
            "matched_criteria": [item.get("label", "") for item in deterministic.get("matched_criteria", []) if isinstance(item, dict)],
            "missing_criteria": [item.get("label", "") for item in deterministic.get("missing_criteria", []) if isinstance(item, dict)],
            "misconceptions": [item.get("label", "") for item in deterministic.get("misconceptions", []) if isinstance(item, dict)],
            "remediation": {key: remediation.get(key, "") for key in ("title", "focus", "retry_prompt")},
            "laya": {"status": laya.get("status", "unknown"), "decision_label": laya.get("decision_label", ""), "agreement": laya.get("agreement", ""), "review_required": bool(laya.get("review_required", False))},
            "source": {key: source.get(key, "") for key in ("file", "locator", "program")},
        }

    def fetch_results(self) -> dict[str, Any]:
        """Importe les résultats via la Web App Apps Script protégée par clé."""
        if not self.configured:
            return {"ok": False, "status": "not_configured", "error": "La Web App Google Sheets n'est pas configurée."}
        parsed = urlparse(self.app_url)
        if parsed.scheme != "https" or parsed.hostname not in {"script.google.com", "script.googleusercontent.com"}:
            return {"ok": False, "status": "invalid_source", "error": "L'URL doit être une Web App Google Apps Script en HTTPS."}
        request = Request(
            self._request_url(action="dashboard"),
            headers={"Accept": "application/json", "User-Agent": "VoixSVT/1.0"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("La réponse Google Sheets dépasse 2 Mo.")
            body = raw.decode("utf-8-sig", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            return {"ok": False, "status": "error", "error": f"Google Sheets a répondu HTTP {exc.code}{f' — {detail}' if detail else ''}."}
        except (TimeoutError, URLError, OSError, ValueError) as exc:
            return {"ok": False, "status": "error", "error": str(exc)[:300]}
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "status": "invalid_response", "error": "La Web App n'a pas renvoyé de JSON exploitable."}
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            error = payload.get("error", "Réponse invalide.") if isinstance(payload, dict) else "Réponse invalide."
            return {"ok": False, "status": "error", "error": str(error)[:300]}
        records = payload.get("records")
        if not isinstance(records, list):
            return {"ok": False, "status": "invalid_response", "error": "La réponse ne contient pas la liste des résultats."}
        return {
            "ok": True,
            "status": "imported",
            "imported_at": datetime.now(UTC).isoformat(),
            "records": [_normalise_record(item) for item in records if isinstance(item, dict)],
            "stats": _normalise_stats(payload.get("stats")),
        }

    def authenticate_teacher(self, access_code: str) -> bool:
        """Compare le code sans révéler son index par un eventail constant."""
        expected = os.environ.get("TEACHER_ACCESS_CODE", "")
        if not expected:
            return False
        return hmac.compare_digest(access_code.encode("utf-8"), expected.encode("utf-8"))

    def make_teacher_token(self, issued_at: int | None = None) -> str:
        secret = os.environ.get("TEACHER_SESSION_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError("TEACHER_SESSION_SECRET doit contenir au moins 32 caractères.")
        issued = int(time.time()) if issued_at is None else int(issued_at)
        claims = json.dumps({"role": "teacher", "iat": issued}, separators=(",", ":"))
        payload = base64.urlsafe_b64encode(claims.encode()).decode().rstrip("=")
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def verify_teacher_token(self, token: str, *, now: int | None = None) -> bool:
        secret = os.environ.get("TEACHER_SESSION_SECRET", "")
        if len(secret) < 32 or not token or token.count(".") != 1:
            return False
        payload, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        try:
            padding = "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload + padding))
            issued = int(claims.get("iat", 0))
        except (ValueError, TypeError, json.JSONDecodeError):
            return False
        current = int(time.time()) if now is None else int(now)
        return claims.get("role") == "teacher" and current >= issued and current - issued < 8 * 60 * 60


def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    timestamp = record.get("timestamp") or record.get("createdAt") or record.get("created_at") or ""
    maximum = _bounded_number(record.get("maxScore") or record.get("max_score") or 4, 1, 4)
    return {
        "analysis_id": str(record.get("analysisId") or record.get("analysis_id") or "")[:100],
        "timestamp": str(timestamp)[:50],
        "first_name": str(record.get("firstName") or record.get("first_name") or "")[:80],
        "last_name": str(record.get("lastName") or record.get("last_name") or "")[:80],
        "class_name": str(record.get("className") or record.get("class_name") or "Non renseignée")[:40],
        "level": str(record.get("level") or "Non renseigné")[:30],
        "school_level": str(record.get("schoolLevel") or record.get("school_level") or "—")[:20],
        "theme": str(record.get("theme") or "Non renseigné")[:160],
        "title": str(record.get("title") or "Question")[:220],
        "question_id": str(record.get("questionId") or record.get("question_id") or "")[:120],
        "transcription": str(record.get("transcription") or "")[:1200],
        "score": _bounded_number(record.get("score"), 0, 4),
        "max_score": maximum,
        "verdict": str(record.get("verdict") or record.get("label") or "Non renseigné")[:160],
        "coverage": _bounded_number(record.get("coverage"), 0, 1),
        "complete": _as_bool(record.get("complete")),
        "contradictory": _as_bool(record.get("contradictory")),
        "matched_criteria": _as_list(record.get("matched_criteria") or record.get("matchedCriteria")),
        "missing_criteria": _as_list(record.get("missing_criteria") or record.get("missingCriteria")),
        "misconceptions": _as_list(record.get("misconceptions")),
        "remediation": str(record.get("remediation") or record.get("remediationTitle") or "")[:240],
        "teacher_review_required": _as_bool(record.get("review") or record.get("teacher_review_required")),
    }




def _normalise_stats(stats: Any) -> dict[str, Any]:
    if not isinstance(stats, dict):
        return {"by_class": [], "by_theme": [], "by_level": []}
    aliases = {"by_class": ("by_class", "byClass"), "by_theme": ("by_theme", "byTheme"), "by_level": ("by_level", "byLevel")}
    normalised: dict[str, Any] = {}
    for output, names in aliases.items():
        source = next((stats.get(name) for name in names if isinstance(stats.get(name), list)), [])
        normalised[output] = [_normalise_group(item) for item in source if isinstance(item, dict)]
    return normalised


def _normalise_group(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(item.get("label") or "Non renseigné")[:180],
        "responses": int(_bounded_number(item.get("responses"), 0, 1_000_000)),
        "average_score": _bounded_number(item.get("averageScore") or item.get("average_score"), 0, 4),
        "average_coverage": _bounded_number(item.get("averageCoverage") or item.get("average_coverage"), 0, 1),
        "complete_rate": _bounded_number(item.get("completeRate") or item.get("complete_rate"), 0, 1),
        "reviews": int(_bounded_number(item.get("reviews"), 0, 1_000_000)),
    }


def _bounded_number(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(minimum)
    if not math.isfinite(number):
        return float(minimum)
    return round(max(minimum, min(maximum, number)), 4)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "oui", "yes", "vrai"}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item)[:240] for item in value[:30]]
    return []


