"""Client robuste du worker JSON-lines de Laya-MLX."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any


class LayaError(RuntimeError):
    """Le worker Laya est indisponible ou a renvoyé une erreur."""


class LayaClient:
    def __init__(
        self,
        python: str | Path,
        worker: str | Path,
        model: str = "aac6fef/laya-multilingual-mlx",
        ready_timeout: float = 300,
        predict_timeout: float = 180,
    ) -> None:
        self.python = Path(python)
        self.worker = Path(worker)
        self.model = model
        self.ready_timeout = ready_timeout
        self.predict_timeout = predict_timeout
        self._process: subprocess.Popen[str] | None = None
        self._start_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._response_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._next_id = 0
        self._ready_info: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return self.python.is_file() and self.worker.is_file()

    @property
    def ready(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "ready": self.ready,
            "model": self.model,
            "device": os.environ.get("LAYA_DEVICE", "cpu"),
            "python": str(self.python),
            "worker": str(self.worker),
            "runtime": "local CPU, JSON-lines",
        }

    def _drain_stderr(self) -> None:
        if not self._process or not self._process.stderr:
            return
        for line in self._process.stderr:
            message = line.rstrip()
            if message:
                print(f"[laya-worker] {message}", flush=True)

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._ready_info = None
        if process is None:
            return
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    def _start(self) -> None:
        if self.ready:
            return
        if not self.available:
            raise LayaError(
                "Laya local introuvable. Vérifiez LAYA_PYTHON et LAYA_WORKER dans app/settings.py."
            )
        with self._start_lock:
            if self.ready:
                return
            self._stop_locked()
            env = os.environ.copy()
            env.update(
                {
                    "LAYA_MODEL": self.model,
                    "LAYA_DEVICE": os.environ.get("LAYA_DEVICE", "cpu"),
                    "LAYA_DTYPE": os.environ.get("LAYA_DTYPE", "float16"),
                    "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", "1"),
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                    "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                }
            )
            try:
                process = subprocess.Popen(
                    [str(self.python), "-u", str(self.worker)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    cwd=str(self.worker.parent),
                    env=env,
                )
            except OSError as exc:
                raise LayaError(f"Impossible de démarrer Laya: {exc}") from exc
            self._process = process
            threading.Thread(target=self._drain_stderr, daemon=True, name="laya-stderr").start()
            try:
                self._ready_info = self._read_ready(process, self.ready_timeout)
            except Exception:
                self._stop_locked()
                raise
            threading.Thread(target=self._read_responses, daemon=True, name="laya-reader").start()

    @staticmethod
    def _read_ready(process: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
        result: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

        def read() -> None:
            assert process.stdout
            result.put(json.loads(process.stdout.readline()))

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise LayaError(f"Laya n'est pas prêt après {timeout:.0f} s")
        try:
            message = result.get_nowait()
        except queue.Empty as exc:
            raise LayaError("Laya s'est arrêté pendant son démarrage") from exc
        if message.get("event") != "ready":
            raise LayaError(message.get("error", "Réponse de démarrage Laya invalide"))
        return message

    def _read_responses(self) -> None:
        assert self._process and self._process.stdout
        for line in self._process.stdout:
            try:
                message = json.loads(line)
                request_id = message.get("id")
            except json.JSONDecodeError:
                continue
            if request_id is None:
                continue
            with self._response_lock:
                waiter = self._pending.get(int(request_id))
            if waiter is not None:
                waiter.put(message)


    def predict(self, question: dict[str, Any], transcription: str) -> dict[str, Any]:
        self._start()
        state = {
            "niveau": question["level"],
            "theme": question["theme"],
            "question": question["prompt"],
            "reponse_eleve": transcription,
            "reponse_attendue": question["expected_answer"],
            "grille_attendue": [item["label"] for item in question["criteria"]],
        }
        questions = {
            "scientificite": {
                "type": "noul",
                "instructions": (
                    "La proposition centrale de la réponse de l'élève est-elle scientifiquement correcte "
                    "pour la question posée ?"
                ),
                "criteria": {
                    "false": "L'élève donne une réponse fausse, une contradiction ou une confusion majeure.",
                    "true": "L'élève donne une réponse globalement correcte pour la question posée.",
                },
            },
            "completude": {
                "type": "noul",
                "instructions": (
                    "La réponse traite-t-elle les éléments attendus de la grille de cette question SVT ?"
                ),
                "criteria": {
                    "false": "Un ou plusieurs éléments attendus manquent ou restent hors sujet.",
                    "true": "La réponse couvre les éléments attendus de la grille.",
                },
            },
        }
        return self._request({"op": "predict", "state": state, "questions": questions})

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._request_lock:
            process = self._process
            if not process or not process.stdin:
                raise LayaError("Le worker Laya n'est pas actif")
            with self._response_lock:
                self._next_id += 1
                request_id = self._next_id
                waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
                self._pending[request_id] = waiter
            try:
                process.stdin.write(json.dumps({"id": request_id, **payload}, ensure_ascii=False) + "\n")
                process.stdin.flush()
                try:
                    message = waiter.get(timeout=self.predict_timeout)
                except queue.Empty as exc:
                    self._stop_locked()
                    raise LayaError(
                        f"Décision Laya dépassée ({self.predict_timeout:.0f} s)"
                    ) from exc
            finally:
                with self._response_lock:
                    self._pending.pop(request_id, None)
        if not message.get("ok"):
            raise LayaError(message.get("error", "Le worker Laya a renvoyé une erreur"))
        return message["result"]

    def shutdown(self) -> None:
        with self._start_lock:
            self._stop_locked()
