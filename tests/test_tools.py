import pytest
import requests

from tools import mandi, weather


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_weather_rejects_blank_place():
    with pytest.raises(weather.WeatherError):
        weather.get_weather("   ")


def test_weather_unknown_place(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(200, {"results": []}))
    with pytest.raises(weather.WeatherError, match="No Indian place"):
        weather.get_weather("Nowhereville")


def test_mandi_missing_key(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "")
    with pytest.raises(mandi.MandiError, match="key is not set"):
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")


def test_mandi_rejects_unsupported_crop(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    with pytest.raises(mandi.MandiError, match="not a supported crop"):
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Wheat")


def test_mandi_error_message_never_contains_key(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "secret-key-123")
    monkeypatch.setattr(mandi.time, "sleep", lambda s: None)

    def always_502(*args, **kwargs):
        return FakeResponse(502)

    monkeypatch.setattr(mandi.requests, "get", always_502)
    with pytest.raises(mandi.MandiError) as info:
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
    assert "secret-key-123" not in str(info.value)
    assert "HTTP 502" in str(info.value)


def test_mandi_no_rows_is_reported(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: FakeResponse(200, {"records": []}))
    with pytest.raises(mandi.MandiError, match="No Potato market prices"):
        mandi.get_mandi_prices("Manipur", "Imphal West", "Potato")


def test_mandi_rate_limit_message(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(
        mandi.requests, "get", lambda *a, **k: FakeResponse(200, {"error": "Rate limit exceeded"})
    )
    with pytest.raises(mandi.MandiError, match="Rate limit exceeded"):
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
