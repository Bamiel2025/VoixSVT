


"""Correction déterministe d'une transcription par une grille de concepts."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_TRANSLATIONS = str.maketrans({"œ": "oe", "æ": "ae", "ø": "oe", "ß": "ss"})


def normalize_text(value: str) -> str:
    """Normalise le français sans perdre les mots utiles à la grille."""
    value = value.translate(_TRANSLATIONS).lower().replace("’", "'").replace(" ", " ")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def tokenize(value: str) -> list[str]:
    normalized = normalize_text(value)
    return normalized.split() if normalized else []


_NEGATIONS = {"ne", "pas", "aucun", "aucune", "jamais", "ni", "sans", "non"}
_CLAUSE_BOUNDARIES = {
    "et",
    "ou",
    "mais",
    "cependant",
    "pourtant",
    "en revanche",
    "par contre",
    "tandis",
    "alors",
}


def _is_negated(haystack: list[str], index: int) -> bool:
    """Indique si la proposition appartient à une négation encore active."""
    for token in reversed(haystack[max(0, index - 12) : index]):
        if token in _CLAUSE_BOUNDARIES:
            return False
        if token in _NEGATIONS:
            return True
    return False


def _find_phrase(haystack: list[str], phrase: str) -> int | None:
    """Trouve une phrase sans compter une mention explicitement niée."""
    needle = tokenize(phrase)
    if not needle or len(needle) > len(haystack):
        return None
    width = len(needle)
    for index in range(len(haystack) - width + 1):
        if haystack[index : index + width] != needle:
            continue
        if _is_negated(haystack, index):
            continue
        return index
    return None


def _contains_phrase(haystack: list[str], phrase: str) -> bool:
    return _find_phrase(haystack, phrase) is not None


def _groups_match(tokens: list[str], groups: list[list[str]]) -> list[str] | None:
    """Un groupe est satisfait lorsqu'une de ses alternatives apparaît."""
    evidence: list[str] = []
    for alternatives in groups:
        matched = next((alt for alt in alternatives if _contains_phrase(tokens, alt)), None)
        if matched is None:
            return None
        evidence.append(matched)
    return evidence


def _criterion_result(criterion: dict[str, Any], tokens: list[str]) -> dict[str, Any]:
    evidence = _groups_match(tokens, criterion["groups"])
    return {
        "id": criterion["id"],
        "label": criterion["label"],
        "weight": float(criterion.get("weight", 1)),
        "required": bool(criterion.get("required", True)),
        "found": evidence is not None,
        "evidence": evidence or [],
        "feedback": criterion.get("feedback", ""),
        "remediation": criterion.get("remediation", ""),
    }


def _misconceptions(question: dict[str, Any], tokens: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in question.get("misconceptions", []):
        evidence = _groups_match(tokens, item["cues"])
        if evidence is not None:
            results.append(
                {
                    "id": item["id"],
                    "label": item["label"],
                    "evidence": evidence,
                    "feedback": item.get("feedback", ""),
                    "remediation": item.get("remediation", ""),
                }
            )
    return results


def _build_remediation(
    question: dict[str, Any],
    missing: list[dict[str, Any]],
    misconceptions: list[dict[str, Any]],
    complete: bool,
) -> dict[str, Any]:
    config = question["remediation"]
    if complete:
        return {
            "title": "Consolider en une phrase",
            "focus": "La réponse est attendue ; travaille maintenant la causalité et la précision.",
            "steps": [
                "Relis ta réponse en cherchant une explication « parce que / donc », pas seulement un vocabulaire.",
                "Reformule l’idée en une phrase complète, puis vérifie qu’elle répond à la question.",
            ],
            "retry_prompt": config["retry_prompt"],
            "micro_activity": config.get(
                "extension", "Invente une seconde question du même type et réponds-y."
            ),
        }

    priority: dict[str, Any] | None = None
    if misconceptions:
        priority = misconceptions[0]
    elif missing:
        priority = missing[0]
    target = priority["label"] if priority else "la réponse attendue"
    steps = [f"Repère d’abord l’élément prioritaire : {target}.", config["micro_task"]]
    if priority and priority.get("remediation"):
        steps.append(priority["remediation"])
    else:
        steps.append("Reprends la réponse modèle et remplace chaque terme par une explication personnelle.")
    steps.append(f"Réessaie : {config['retry_prompt']}")
    return {
        "title": "Remédiation ciblée",
        "focus": f"Priorité : {target}.",
        "steps": steps,
        "retry_prompt": config["retry_prompt"],
        "micro_activity": config.get(
            "extension", "Demande à un camarade de dessiner le lien entre les deux idées."
        ),
    }


def grade_answer(question: dict[str, Any], transcription: str) -> dict[str, Any]:
    """Compare la transcription à la grille, sans faire appel à un modèle."""
    text = re.sub(r"\s+", " ", transcription).strip()
    tokens = tokenize(text)
    criteria = [_criterion_result(item, tokens) for item in question["criteria"]]
    misconceptions = _misconceptions(question, tokens)
    matched = [item for item in criteria if item["found"]]
    missing = [item for item in criteria if not item["found"]]

    total_weight = sum(item["weight"] for item in criteria) or 1.0
    coverage = sum(item["weight"] for item in matched) / total_weight
    required_missing = any(item["required"] for item in missing)
    complete = not missing and not misconceptions
    contradictory = bool(misconceptions)
    empty = not tokens

    if empty:
        level, label, verdict = 0, "Réponse vide", "empty"
        feedback = "Aucune parole n’a été transcrite. Refaites l’enregistrement ou saisissez une réponse."
    elif contradictory:
        level, label, verdict = 0, "Confusion à reprendre", "misconception"
        feedback = misconceptions[0].get("feedback") or "La réponse contient une idée scientifique à revoir."
    elif complete:
        level, label, verdict = 4, "Réponse attendue", "complete"
        feedback = "Les éléments attendus de la grille sont présents."
    elif coverage >= 0.6 and not required_missing:
        level, label, verdict = 3, "Presque complète", "almost_complete"
        feedback = "L’idée centrale est juste, mais la réponse reste incomplète."
    elif matched or coverage > 0:
        level, label, verdict = 2 if coverage >= 0.4 else 1, "Réponse partielle", "partial"
        feedback = "Une partie de la réponse est pertinente, mais un concept attendu manque."
    else:
        level, label, verdict = 0, "Réponse insuffisante", "insufficient"
        feedback = "La réponse ne contient pas encore les concepts attendus par cette grille."

    sentence_count = len([part for part in re.split(r"[.!?]+", text) if part.strip()])
    return {
        "engine": "grille-deterministe",
        "coverage": round(coverage, 3),
        "level": level,
        "max_level": 4,
        "label": label,
        "verdict": verdict,
        "feedback": feedback,
        "matched_criteria": matched,
        "missing_criteria": missing,
        "misconceptions": misconceptions,
        "contradictory": contradictory,
        "complete": complete,
        "statistics": {
            "characters": len(text),
            "words": len(tokens),
            "sentences": sentence_count,
            "too_long": sentence_count > 2 or len(tokens) > 55,
        },
        "remediation": _build_remediation(question, missing, misconceptions, complete),
    }

