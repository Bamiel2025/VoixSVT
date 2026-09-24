# Repository Guidelines

## Project Structure & Module Organization

`app/main.py` exposes the local FastAPI server, static interface, upload endpoint, and background Laya jobs. `app/grader.py` owns deterministic keyword-grid scoring; `app/laya_client.py` manages the persistent JSON-lines worker from `D:\IA\laramxl`; `app/transcription.py` wraps local Faster-Whisper. Question banks and expected concepts live in `app/data/questions_*.json`, while the no-build frontend is split across `app/static/index.html`, `styles.css`, and `app.js`. Tests mirror these responsibilities in `tests/test_grader.py` and `tests/test_api.py`.

## Build, Test, and Development Commands

- `.\install.ps1` — create `.venv` with Python 3.11 and install the editable project plus test tools.
- `.\start.ps1` — serve the app at `http://127.0.0.1:8765`.
- `.\.venv\Scripts\python.exe -m pytest` — run the full test suite.
- `.\.venv\Scripts\python.exe -m pytest tests/test_grader.py` — run deterministic grading tests only.
- `.\.venv\Scripts\python.exe -m ruff check app tests` — lint Python sources.
- `.\.venv\Scripts\python.exe -m app.main` — start the server without the PowerShell wrapper.

## Coding Style & Naming Conventions

Use four-space indentation, type hints for public functions, and PEP 8 names: `snake_case` for functions and variables, `PascalCase` for classes. Keep FastAPI routes in `app/main.py` thin; place matching or scoring logic in its own module. JSON and JavaScript use UTF-8. No remote fonts, CDNs, or AI APIs are used. The optional Google Apps Script export is the sole intentional network integration and must remain opt-in through `GOOGLE_SHEETS_APP_URL`. Ruff is the configured Python linter with its default rule set.

## Testing Guidelines

Every grading change must include a positive, partial, misconception, and negation case as appropriate. API tests must use `TestClient`; replace heavyweight Whisper/Laya calls with test doubles rather than loading the real models. Keep tests deterministic and independent of network access. Name files `test_*.py` and test functions `test_<behavior>()`.

## Space enseignant

- Le code d’accès et les secrets de production ne sont jamais versionnés dans Git.
- `app/main.py` expose la session enseignant, les routes d’import et le mode hébergé ; `app/sheets_client.py` normalise et protège le contrat Google Sheets.
- L’import et les statistiques sont vérifiés côté serveur avant d’être rendus au frontend.

## Commit and Pull Request Guidelines

Ce dépôt utilise des commits concis à l’impératif, par exemple `Add teacher results dashboard`. Ne jamais committer `.venv/`, les journaux, les captures, `.env`, `.vercel/` ou des réponses élèves.
