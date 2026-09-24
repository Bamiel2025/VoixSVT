"""Point d'entrée ASGI utilisé par Vercel.

Vercel charge la variable ``app`` depuis ``api/index.py``. L'application locale
continue d'être lancée avec ``python -m app.main``.
"""

from app.main import app

__all__ = ["app"]
