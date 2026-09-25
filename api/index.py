"""Point d'entrée ASGI utilisé par Vercel.

Vercel charge ce fichier par chemin (``spec_from_file_location``) avec un
``sys.path`` qui ne contient que les dépendances : la racine du projet doit
donc être réinjectée avant d'importer l'application. En cas d'échec, le rapport
complet est renvoyé dans la réponse HTTP, la fonction n'ayant pas de journaux
consultables.

L'application locale continue d'être lancée avec ``python -m app.main``.
"""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


async def send_text(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def serve_lifespan(receive: Receive, send: Send) -> None:
    while True:
        message = await receive()
        if message.get("type") == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message.get("type") == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


def diagnostic_app(report: str) -> Any:
    """Application ASGI de repli qui répond ``500`` avec ``report``."""

    body = report.encode("utf-8", "replace")

    async def app(scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await serve_lifespan(receive, send)
            return
        await send_text(send, 500, body)

    return app


def startup_report(label: str) -> str:
    """Construit le rapport affiché quand le démarrage hébergé échoue."""
    signals = {
        name: os.environ.get(name)
        for name in ("HOSTED_MODE", "VERCEL", "VERCEL_ENV", "__VC_HANDLER_MODULE_NAME")
    }
    return (
        f"{label}\n\n"
        f"Python {sys.version.split()[0]}\n"
        f"Signaux d'hébergement : {signals}\n"
        f"sys.path : {os.pathsep.join(sys.path)}\n\n"
        f"{traceback.format_exc()}"
    )


try:
    from app.main import app as _application
except BaseException:  # noqa: BLE001 — aucun journal disponible, on répond.
    _application = diagnostic_app(startup_report("Échec de l'import de app.main"))

# Assignation au premier niveau : l'analyse Vercel doit trouver `app` ici.
app = _application

__all__ = ["app", "diagnostic_app", "startup_report"]
