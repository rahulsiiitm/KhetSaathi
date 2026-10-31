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


def test_crop_name_too_short_rejected():
    response = client.post("/advise", json={**VALID, "crop": "P"})
    assert response.status_code == 422


def test_any_crop_name_is_accepted_and_reported_honestly_when_missing(monkeypatch):
    # A crop outside the seed list is allowed; the market lookup then says no data was found.
    import agent
    monkeypatch.setattr(app_module, "advise", lambda *a, **k: {"advice": "x", "sources": [], "warnings": [], "trace": []})
    response = client.post("/advise", json={**VALID, "crop": "Wheat"})
    assert response.status_code == 200


def test_crops_endpoint_lists_seed_crops():
    response = client.get("/crops")
    assert response.status_code == 200
    assert "Potato" in response.json()["crops"] and "Wheat" in response.json()["crops"]


def test_locate_rejects_out_of_range_coordinates():
    response = client.post("/locate", json={"latitude": 200, "longitude": 75})
    assert response.status_code == 422


def test_missing_gemini_key_returns_503(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    response = client.post("/advise", json=VALID)
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
