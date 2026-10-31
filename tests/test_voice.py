import pytest
from fastapi.testclient import TestClient

import app as app_module
from tools import voice


class FakeResponse:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_no_key_gives_a_clear_fallback_message(monkeypatch):
    monkeypatch.setenv("VOICE_API", "")
    with pytest.raises(voice.VoiceError, match="not set up"):
        voice.synthesize("Irrigate today.")


def test_free_plan_gets_the_paid_plan_message_and_no_key(monkeypatch):
    monkeypatch.setenv("VOICE_API", "secret-voice-key-999")
    monkeypatch.setattr(voice.requests, "post", lambda *a, **k: FakeResponse(
        402, {"detail": {"code": "paid_plan_required"}}))
    with pytest.raises(voice.VoiceError) as info:
        voice.synthesize("Irrigate today.")
    assert "paid ElevenLabs plan" in str(info.value)
    assert "secret-voice-key-999" not in str(info.value)


def test_successful_response_returns_audio_and_sends_key_in_header(monkeypatch):
    monkeypatch.setenv("VOICE_API", "test-key")
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["headers"] = headers
        sent["url"] = url
        return FakeResponse(200, content=b"ID3-audio")

    monkeypatch.setattr(voice.requests, "post", fake_post)
    assert voice.synthesize("आज सिंचाई करें") == b"ID3-audio"
    assert sent["headers"]["xi-api-key"] == "test-key"
    assert "test-key" not in sent["url"]  # the key never goes in the URL


def test_speak_endpoint_returns_503_when_voice_is_unavailable(monkeypatch):
    monkeypatch.setenv("VOICE_API", "")
    client = TestClient(app_module.app)
    response = client.post("/speak", json={"text": "Irrigate today."})
    assert response.status_code == 503
    assert "phone's voice" in response.json()["detail"]


def test_speak_endpoint_rejects_empty_text():
    client = TestClient(app_module.app)
    assert client.post("/speak", json={"text": ""}).status_code == 422
