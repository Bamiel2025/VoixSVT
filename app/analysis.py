"""Stockage en mémoire et interprétation pédagogique des décisions Laya."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AnalysisStore:
    """Conserve les analyses de la session sans écrire les copies sur disque."""

    def __init__(self, max_items: int = 200) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.max_items = max_items

    def create(self, analysis: dict[str, Any]) -> None:
        with self._lock:
            if len(self._items) >= self.max_items:
                oldest = min(self._items, key=lambda key: self._items[key]["created_at"])
                self._items.pop(oldest, None)
            self._items[analysis["id"]] = analysis

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(analysis_id)
            return dict(item) if item else None

    def update_laya(self, analysis_id: str, laya: dict[str, Any]) -> None:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None:
                return
            item["laya"] = laya
            item["updated_at"] = utc_now()

    def update_sheets(self, analysis_id: str, sheets: dict[str, Any]) -> None:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None:
                return
            item["sheets"] = sheets
            item["updated_at"] = utc_now()


def interpret_laya(raw: dict[str, Any], deterministic: dict[str, Any]) -> dict[str, Any]:
    """Traduit les deux têtes `noul` en indices, sans transformer la note."""
    answers = raw.get("answers", {})

    def metric(name: str) -> tuple[float, float]:
        answer = answers.get(name, {})
        probability = float(answer.get("noul", 0.5))
        confidence = float(answer.get("confidence", 0.0))
        return max(0.0, min(1.0, probability)), max(0.0, min(1.0, confidence))

    science, science_confidence = metric("scientificite")
    completeness, completeness_confidence = metric("completude")
    expected_complete = deterministic["complete"]
    predicted_complete = completeness >= 0.5
    grid_score = deterministic["level"]
    agreement = "concordant" if predicted_complete == expected_complete else "discordant"

    low_confidence = min(science_confidence, completeness_confidence) < 0.4
    strong_conflict = (grid_score >= 3 and science < 0.35) or (
        deterministic["contradictory"] and science > 0.65
    )
    review_required = low_confidence or strong_conflict or agreement == "discordant"

    if review_required:
        decision_label = "Relecture conseillée"
        summary = (
            "Laya et la grille ne concordent pas nettement, ou la confiance est faible. "
            "La grille déterministe reste prioritaire et l’énoncé doit être relu."
        )
    elif expected_complete and science >= 0.5 and completeness >= 0.5:
        decision_label = "Indices concordants"
        summary = "Laya renforce la lecture de la grille sans la remplacer."
    else:
        decision_label = "Diagnostic à nuancer"
        summary = "Laya confirme surtout qu’une vérification humaine reste nécessaire."

    return {
        "status": "complete",
        "decision_label": decision_label,
        "summary": summary,
        "metrics": {
            "scientificite": {
                "probabilite_vrai": round(science, 3),
                "confidence": round(science_confidence, 3),
            },
            "completude": {
                "probabilite_vrai": round(completeness, 3),
                "confidence": round(completeness_confidence, 3),
            },
        },
        "agreement": agreement,
        "review_required": review_required,
        "authoritative": False,
        "raw": raw,
        "completed_at": utc_now(),
    }
