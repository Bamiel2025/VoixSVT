import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main_module


class FakeWhisper:
    installed = True
    loaded = True

    def status(self) -> dict[str, Any]:
        return {"installed": True, "loaded": True, "model": "test"}

    def transcribe(self, _: Path) -> dict[str, Any]:
        return {"text": "Les nutriments passent dans le sang au niveau des villosités.", "model": "test"}


class FakeLaya:
    available = False
    ready = False

    def status(self) -> dict[str, Any]:
        return {"available": False, "ready": False, "model": "test"}

    def predict(self, *_: Any) -> dict[str, Any]:
        raise AssertionError("Laya ne doit pas être appelé par ce test")

    def shutdown(self) -> None:
        pass


class FakeSheets:
    configured = False
    app_url = ""

    def status(self) -> dict[str, Any]:
        return {"configured": False, "label": "Non configuré"}

    def send_analysis(self, _: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("Google Sheets ne doit pas être appelé sans URL")

    def authenticate_teacher(self, access_code: str) -> bool:
        return access_code == os.environ.get("TEACHER_ACCESS_CODE", "")

    def make_teacher_token(self, issued_at: int | None = None) -> str:
        secret = os.environ.get("TEACHER_SESSION_SECRET", "")
        issued = int(time.time()) if issued_at is None else int(issued_at)
        payload = base64.urlsafe_b64encode(
            json.dumps({"role": "teacher", "iat": issued}, separators=(",", ":")).encode()
        ).decode().rstrip("=")
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
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            issued = int(claims.get("iat", 0))
        except (ValueError, TypeError, json.JSONDecodeError):
            return False
        current = int(time.time()) if now is None else int(now)
        return claims.get("role") == "teacher" and current >= issued and current - issued < 8 * 60 * 60


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main_module, "whisper", FakeWhisper())
    monkeypatch.setattr(main_module, "laya", FakeLaya())
    monkeypatch.setattr(main_module, "sheets", FakeSheets())
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_health_et_questions(client: TestClient):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["audio_processing_local"] is True
    assert health.json()["questions"] == 87
    assert health.json()["results_export_configured"] is False

    catalog = client.get("/api/questions").json()
    assert catalog["count"] == 87
    by_id = {item["id"]: item for item in catalog["questions"]}
    assert by_id["c4-digestion-absorption"]["level"] == "Cycle 4"
    assert by_id["c4-digestion-absorption"]["school_level"] == "5e"
    assert by_id["c4-digestion-enzymes"]["level"] == "Cycle 4"
    assert by_id["c4-digestion-enzymes"]["school_level"] == "5e"
    assert by_id["c4-vent-direction"]["level"] == "Cycle 4"
    assert by_id["c4-vent-direction"]["school_level"] == "4e"


def test_analyse_deterministe_sans_laya(client: TestClient):
    response = client.post(
        "/api/analyze",
        json={
            "question_id": "c4-digestion-absorption",
            "transcription": "Dans les villosités de l'intestin grêle, les nutriments passent dans le sang.",
            "use_laya": True,
            "student_first_name": " Léa ",
            "student_last_name": "Martin",
            "student_class": "5e2",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deterministic"]["complete"] is True
    assert payload["student"] == {"first_name": "Léa", "last_name": "Martin", "class_name": "5e2"}
    assert payload["sheets"]["status"] == "not_configured"
    assert payload["laya"]["status"] == "unavailable"
    assert client.get(f"/api/analysis/{payload['id']}").status_code == 200


def test_identite_obligatoire_et_non_espaciale(client: TestClient):
    base = {
        "question_id": "c4-digestion-absorption",
        "transcription": "Les nutriments passent dans le sang.",
        "use_laya": False,
        "student_first_name": "Léa",
        "student_last_name": "Martin",
        "student_class": "5e2",
    }
    missing = {key: value for key, value in base.items() if key != "student_class"}
    assert client.post("/api/analyze", json=missing).status_code == 422
    blank = {**base, "student_class": "   "}
    assert client.post("/api/analyze", json=blank).status_code == 422


def test_transcription_utilise_service_local(client: TestClient):
    response = client.post(
        "/api/transcribe",
        files={"file": ("reponse.webm", b"not-a-real-webm", "audio/webm")},
    )
    assert response.status_code == 200
    assert response.json()["text"].startswith("Les nutriments")


def test_page_et_assets_ont_entetes_confidentialite(client: TestClient):
    page = client.get("/")
    assert page.status_code == 200
    assert "Voix SVT" in page.text
    assert "Permissions-Policy" in page.headers
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert client.get("/static/app.js").status_code == 200


def test_question_inexistante(client: TestClient):
    response = client.post(
        "/api/analyze",
        json={
            "question_id": "inconnue",
            "transcription": "Une réponse",
            "use_laya": False,
            "student_first_name": "Léa",
            "student_last_name": "Martin",
            "student_class": "5e2",
        },
    )
    assert response.status_code == 404


def test_catalog_masque_la_reponse_de_reference(client: TestClient):
    catalog = client.get("/api/questions").json()
    assert catalog["count"] == 87
    for item in catalog["questions"]:
        assert "expected_answer" not in item
        assert "criteria" not in item
        assert "misconceptions" not in item
        assert item["prompt"].strip().endswith("?")
    detail = client.get("/api/questions/c4-digestion-absorption").json()
    assert "expected_answer" not in detail
    assert detail["prompt"]
    assert detail["context"]


def test_reponse_de_reference_reservee_au_professeur(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TEACHER_ACCESS_CODE", "code-de-test")
    monkeypatch.setenv("TEACHER_SESSION_SECRET", "r" * 32)

    assert client.post("/api/questions/c4-digestion-absorption/reference", json={}).status_code == 401
    wrong = client.post(
        "/api/questions/c4-digestion-absorption/reference",
        json={"access_code": "incorrect"},
    )
    assert wrong.status_code == 401
    assert "expected_answer" not in wrong.json()

    granted = client.post(
        "/api/questions/c4-digestion-absorption/reference",
        json={"access_code": "code-de-test"},
    )
    assert granted.status_code == 200
    assert granted.json()["expected_answer"]

    login = client.post("/api/teacher/login", json={"access_code": "code-de-test"})
    assert login.status_code == 200
    session_only = client.post("/api/questions/c4-digestion-absorption/reference", json={})
    assert session_only.status_code == 200
    assert session_only.json()["id"] == "c4-digestion-absorption"

    assert client.post("/api/questions/inconnue/reference", json={}).status_code == 404


def test_teacher_space_requires_valid_code_and_signed_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TEACHER_ACCESS_CODE", "code-de-test")
    monkeypatch.setenv("TEACHER_SESSION_SECRET", "s" * 32)
    assert client.get("/api/teacher/session").json() == {"authenticated": False}
    assert client.post("/api/teacher/import").status_code == 401
    assert client.post("/api/teacher/login", json={"access_code": "incorrect"}).status_code == 401
    response = client.post("/api/teacher/login", json={"access_code": "code-de-test"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "voix_teacher=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert client.get("/api/teacher/session").json() == {"authenticated": True}
    logout = client.post("/api/teacher/logout")
    assert logout.status_code == 200
    assert client.get("/api/teacher/session").json() == {"authenticated": False}


def test_teacher_import_is_server_protected_and_normalises_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.sheets_client import (
        GoogleSheetsClient,
        _normalise_record,
        _normalise_stats,
    )

    monkeypatch.setenv("TEACHER_ACCESS_CODE", "code-de-test")
    monkeypatch.setenv("TEACHER_SESSION_SECRET", "t" * 32)
    token = GoogleSheetsClient().make_teacher_token()
    client.cookies.set("voix_teacher", token)

    raw = {
        "ok": True,
        "records": [
            {
                "analysisId": "abc",
                "timestamp": "2026-09-24T12:00:00.000Z",
                "firstName": "Léa",
                "lastName": "Martin",
                "className": "5e2",
                "level": "Cycle 4",
                "schoolLevel": "5e",
                "theme": "Digestion",
                "title": "Passage des nutriments",
                "score": 3,
                "maxScore": 4,
                "verdict": "Réponse attendue",
                "coverage": 0.75,
                "complete": True,
                "contradictory": False,
                "matchedCriteria": ["Critère 1"],
                "missingCriteria": [],
                "misconceptions": [],
                "remediation": "Reformuler",
                "review": False,
            }
        ],
        "stats": {
            "byClass": [
                {
                    "label": "5e2",
                    "responses": 1,
                    "averageScore": 3,
                    "averageCoverage": 0.75,
                    "completeRate": 1,
                    "reviews": 0,
                }
            ]
        },
    }

    class ConfiguredSheets(GoogleSheetsClient):
        def __init__(self) -> None:
            super().__init__("https://script.google.com/macros/s/test/exec?key=secret", 2)

        def fetch_results(self) -> dict[str, Any]:
            return {
                "ok": True,
                "status": "imported",
                "imported_at": "2026-09-24T12:01:00+00:00",
                "records": [_normalise_record(raw["records"][0])],
                "stats": _normalise_stats(raw["stats"]),
            }

    monkeypatch.setattr(main_module, "sheets", ConfiguredSheets())
    response = client.post("/api/teacher/import")
    assert response.status_code == 200
    payload = response.json()
    assert payload["records"][0]["first_name"] == "Léa"
    assert payload["records"][0]["coverage"] == 0.75
    assert payload["stats"]["by_class"][0]["label"] == "5e2"


def test_export_google_sheets_est_opt_in_et_ne_divulgue_pas_la_reponse_brute():
    from app.sheets_client import GoogleSheetsClient

    client = GoogleSheetsClient()
    assert client.configured is False
    assert client.send_analysis({})["status"] == "not_configured"

    question = main_module.get_question("c4-digestion-absorption")
    assert question is not None
    analysis = {
        "id": "a" * 32,
        "created_at": "2026-09-24T12:00:00+00:00",
        "updated_at": "2026-09-24T12:00:00+00:00",
        "student": {"first_name": "Léa", "last_name": "Martin", "class_name": "5e2"},
        "question": question,
        "transcription": "Les villosités permettent le passage des nutriments dans le sang.",
        "deterministic": main_module.grade_answer(
            question,
            "Les nutriments passent dans le sang au niveau des villosités de l’intestin grêle.",
        ),
        "laya": {
            "status": "complete",
            "decision_label": "Indices concordants",
            "agreement": "concordant",
            "review_required": False,
        },
        "teacher_review_required": False,
    }
    payload = client.build_payload(analysis)
    assert payload["schema"] == "voix-svt-analysis-v1"
    assert payload["student"] == {"first_name": "Léa", "last_name": "Martin", "class_name": "5e2"}
    assert payload["question"]["id"] == "c4-digestion-absorption"
    assert payload["result"]["score"] == 4
    assert payload["result"]["coverage"] == 1.0
    assert payload["laya"]["status"] == "complete"


def test_script_apps_script_contient_le_tableau_de_bord():
    script = (Path(__file__).resolve().parents[1] / "apps-script" / "Code.gs").read_text(encoding="utf-8-sig")
    for function_name in (
        "function doPost(e)",
        "function validatePayload_",
        "function upsertResult_",
        "function computeStats_",
        "function writeStatistics_",
    ):
        assert function_name in script
    assert "assertAuthorized_(e);" in script
    assert "WEB_APP_SECRET absent" in script
    assert "getSheetByName(APP.resultsSheet)" in script
    assert "safeCell_" in script


def test_frontend_est_utf8_sans_mojibake():
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    for name in ("index.html", "styles.css", "app.js"):
        text = (static / name).read_text(encoding="utf-8-sig")
        assert "�" not in text
        assert "â€™" not in text
        assert "Ã©" not in text
    script = (static / "app.js").read_text(encoding="utf-8-sig")
    assert "Analyse en cours…" in script
    assert "Correction déterministe terminée" in script
    assert "Analyse complémentaire désactivée" in script
    assert "disabled = false;" in script
    assert 'student_first_name: state.student.first_name' in script
    assert 'el("student-form").addEventListener("submit"' in script
    assert 'return String(input.value).trim().replace(/\\s+/g, " ");' in script
    styles = (static / "styles.css").read_text(encoding="utf-8-sig")
    assert "[hidden] { display: none !important; }" in styles
    page = (static / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="welcome-view"' in page
    assert 'id="assessment-view" hidden' in page


def test_package_application_est_importable():
    from app import __version__

    assert __version__ == "0.1.0"


def test_mode_hote_detecte_sans_variable_vercel(tmp_path: Path):
    from app.settings import detect_hosted_mode

    assert detect_hosted_mode(env={}, root=tmp_path) is False
    assert detect_hosted_mode(env={"HOSTED_MODE": "false"}, root=tmp_path) is False
    assert detect_hosted_mode(env={"VERCEL": "1"}, root=tmp_path) is True
    assert detect_hosted_mode(env={"VERCEL": ""}, root=tmp_path) is False
    assert detect_hosted_mode(env={"HOSTED_MODE": "true"}, root=tmp_path) is True
    assert detect_hosted_mode(env={"__VC_HANDLER_MODULE_NAME": "api.index"}, root=tmp_path) is True
    assert detect_hosted_mode(env={}, root=tmp_path / "lecture-seule") is True


def test_demarrage_ignore_un_dossier_audio_inaccessible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    blocker = tmp_path / "blocage"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(main_module, "HOSTED_MODE", False)
    monkeypatch.setattr(main_module, "UPLOAD_DIR", blocker / "uploads")
    with TestClient(main_module.app) as local_client:
        assert local_client.get("/api/health").status_code == 200
        assert local_client.get("/").status_code == 200


def test_reecriture_vercel_conserve_le_chemin_d_origine():
    config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text(encoding="utf-8"))
    rewrites = config["rewrites"]
    assert len(rewrites) == 1
    assert rewrites[0]["source"] == "/(.*)"
    assert rewrites[0]["destination"] == "/api"
    assert {"type": "request.path", "op": "set", "args": "/$1"} in rewrites[0]["transforms"]


def test_point_entree_vercel_reinjecte_la_racine_du_projet():
    import sys as sys_module

    import api.index as entrypoint

    assert str(entrypoint.ROOT) in sys_module.path
    assert entrypoint.app is not None


def test_point_entree_vercel_signale_un_import_en_echec():
    import asyncio

    from api.index import diagnostic_app

    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(diagnostic_app("rapport d'échec")({"type": "http"}, None, send))

    assert messages[0]["status"] == 500
    assert messages[1]["body"] == "rapport d'échec".encode()


def test_regle_d_environnement_vide_ou_invalide_utilise_le_defaut(monkeypatch: pytest.MonkeyPatch):
    from app.settings import env_float, env_int, env_value

    monkeypatch.setenv("VOIX_TEST_TIMEOUT", "")
    assert env_value("VOIX_TEST_TIMEOUT", "10") == "10"
    assert env_float("VOIX_TEST_TIMEOUT", 10.0) == 10.0
    assert env_int("VOIX_TEST_TIMEOUT", 7) == 7

    monkeypatch.setenv("VOIX_TEST_TIMEOUT", "   ")
    assert env_float("VOIX_TEST_TIMEOUT", 10.0) == 10.0

    monkeypatch.setenv("VOIX_TEST_TIMEOUT", "abc")
    assert env_float("VOIX_TEST_TIMEOUT", 10.0) == 10.0
    assert env_int("VOIX_TEST_TIMEOUT", 7) == 7

    monkeypatch.setenv("VOIX_TEST_TIMEOUT", " 7.5 ")
    assert env_float("VOIX_TEST_TIMEOUT", 10.0) == 7.5


def test_import_des_reglages_avec_variables_vides(monkeypatch: pytest.MonkeyPatch):
    import importlib

    import app.settings as settings_module

    monkeypatch.setenv("GOOGLE_SHEETS_TIMEOUT", "")
    monkeypatch.setenv("MAX_AUDIO_SECONDS", "")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "")
    monkeypatch.setenv("LAYA_MODEL", "")
    reloaded = importlib.reload(settings_module)

    assert reloaded.GOOGLE_SHEETS_TIMEOUT == 10.0
    assert reloaded.MAX_AUDIO_SECONDS == 45.0
    assert reloaded.MAX_UPLOAD_BYTES == 20 * 1024 * 1024
    assert reloaded.LAYA_MODEL == "aac6fef/laya-multilingual-mlx"


def test_cle_web_app_lue_dans_lenvironnement(monkeypatch: pytest.MonkeyPatch):
    from urllib.parse import parse_qsl, urlparse

    from app.sheets_client import GoogleSheetsClient

    base = "https://script.google.com/macros/s/ABC/exec"
    client = GoogleSheetsClient(base)
    monkeypatch.delenv("WEB_APP_SECRET", raising=False)

    assert client._request_url() == base
    assert client._request_url(action="dashboard") == f"{base}?action=dashboard"

    monkeypatch.setenv("WEB_APP_SECRET", "  cle-secrete  ")
    query = dict(parse_qsl(urlparse(client._request_url(action="dashboard")).query))
    assert query == {"key": "cle-secrete", "action": "dashboard"}

    # Une clé déjà présente dans l'URL prime sur l'environnement.
    with_key = GoogleSheetsClient(f"{base}?key=url")
    assert with_key._request_url() == f"{base}?key=url"
