"""Transcription française locale avec Faster-Whisper."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class TranscriptionError(RuntimeError):
    """L'audio ne peut pas être analysé ou transcrit."""


class WhisperService:
    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        max_duration: float = 45,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.max_duration = max_duration
        self._model: Any = None

    @property
    def installed(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def status(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "loaded": self.loaded,
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "language": "fr",
            "privacy": "inférence locale",
            "max_duration_seconds": self.max_duration,
        }

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        if not self.installed:
            raise TranscriptionError(
                "Faster-Whisper n'est pas installé. Exécutez D:\\IA\\CorrecteurAuto\\install.ps1."
            )
        try:
            from faster_whisper import WhisperModel

            threads = max(1, min(6, (os.cpu_count() or 4) - 1))
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=threads,
                num_workers=1,
            )
        except Exception as exc:  # Les erreurs de chargement modele sont techniques.
            raise TranscriptionError(
                f"Impossible de charger Whisper « {self.model_name} ». Le modèle doit être disponible "
                "dans le cache Hugging Face local. Détail: " + str(exc)
            ) from exc
        return self._model

    @staticmethod
    def _probe_duration(path: Path) -> float | None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            if result.returncode != 0:
                return None
            return float(json.loads(result.stdout)["format"]["duration"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired):
            return None

    def transcribe(self, path: Path) -> dict[str, Any]:
        path = Path(path)
        if not path.is_file() or path.stat().st_size == 0:
            raise TranscriptionError("Le fichier audio est vide ou introuvable.")

        duration = self._probe_duration(path)
        if duration is not None and duration > self.max_duration:
            raise TranscriptionError(
                f"Audio trop long ({duration:.1f} s). Limite : {self.max_duration:.0f} s maximum."
            )

        model = self._load()
        try:
            segments, info = model.transcribe(
                str(path),
                language="fr",
                beam_size=3,
                best_of=3,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 350},
                condition_on_previous_text=True,
                temperature=0,
            )
            collected = [
                {"start": round(float(segment.start), 2), "end": round(float(segment.end), 2), "text": segment.text.strip()}
                for segment in segments
                if segment.text and segment.text.strip()
            ]
        except Exception as exc:
            raise TranscriptionError(f"Transcription impossible: {exc}") from exc

        transcript = " ".join(segment["text"] for segment in collected).strip()
        detected_duration = float(getattr(info, "duration", duration or 0.0))
        if detected_duration > self.max_duration:
            raise TranscriptionError(
                f"Audio trop long ({detected_duration:.1f} s). Limite : {self.max_duration:.0f} s."
            )
        if not transcript:
            raise TranscriptionError(
                "Aucune parole claire n’a été détectée. Rapprochez-vous du micro et recommencez."
            )
        return {
            "text": transcript,
            "language": getattr(info, "language", "fr"),
            "language_probability": round(float(getattr(info, "language_probability", 0.0)), 3),
            "duration": round(detected_duration, 2),
            "segments": collected,
            "model": self.model_name,
        }
