"""Chargement et validation de la banque de questions SVT."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_DIR = Path(__file__).resolve().parent / "data"
CATALOG_GLOB = "questions_*.json"


@lru_cache(maxsize=1)
def load_catalog() -> tuple[dict[str, Any], ...]:
    """Charge la banque embarquée et refuse les grilles incomplètes."""
    paths = sorted(CATALOG_DIR.glob(CATALOG_GLOB))
    if not paths:
        raise RuntimeError(f"No question bank found in: {CATALOG_DIR}")
    questions: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid question bank {path.name}: {exc}") from exc
        file_questions = payload.get("questions") if isinstance(payload, dict) else None
        if not isinstance(file_questions, list):
            raise TypeError(f"{path.name} must contain a 'questions' list")
        questions.extend(file_questions)
    if not questions:
        raise RuntimeError("The question bank must contain at least one question")

    seen: set[str] = set()
    required = {
        "id",
        "level",
        "school_level",
        "theme",
        "title",
        "prompt",
        "expected_answer",
        "criteria",
        "remediation",
        "source",
    }
    for question in questions:
        if not isinstance(question, dict):
            raise TypeError("Each question must be a JSON object")
        missing = sorted(required - question.keys())
        if missing:
            raise RuntimeError(f"Question {question.get('id', '?')} misses: {', '.join(missing)}")
        qid = str(question["id"])
        if qid in seen:
            raise RuntimeError(f"Duplicate question id: {qid}")
        seen.add(qid)
        if not isinstance(question["criteria"], list) or not question["criteria"]:
            raise RuntimeError(f"Question {qid} must have criteria")
        for criterion in question["criteria"]:
            groups = criterion.get("groups")
            if (
                not criterion.get("id")
                or not criterion.get("label")
                or not isinstance(groups, list)
                or not groups
                or any(not isinstance(group, list) or not group for group in groups)
            ):
                raise RuntimeError(f"Invalid criterion in question {qid}")

    return tuple(questions)


def get_question(question_id: str) -> dict[str, Any] | None:
    return next((question for question in load_catalog() if question["id"] == question_id), None)


def catalog_summary() -> dict[str, list[str]]:
    questions = load_catalog()
    return {
        "levels": sorted({str(question["level"]) for question in questions}),
        "themes": sorted({str(question["theme"]) for question in questions}),
        "school_levels": sorted({str(question["school_level"]) for question in questions}),
    }
