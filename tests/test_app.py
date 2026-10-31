from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)

VALID = {
    "question": "Should I spray my potato crop this week?",
    "place": "Ludhiana",
    "state": "Punjab",
    "crop": "Potato",
}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_home_page_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "KhetSaathi" in response.text


def test_blank_question_rejected():
    response = client.post("/advise", json={**VALID, "question": "   "})
    assert response.status_code == 422


def test_unknown_crop_rejected():
    response = client.post("/advise", json={**VALID, "crop": "Wheat"})
    assert response.status_code == 422


def test_missing_gemini_key_returns_503(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    response = client.post("/advise", json=VALID)
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
