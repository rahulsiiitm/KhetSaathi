import pytest
import requests

from tools import mandi, weather
from tools.cache import SourceDown


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    monkeypatch.setattr(mandi.time, "sleep", lambda s: None)


def test_weather_rejects_blank_place():
    with pytest.raises(weather.WeatherError):
        weather.get_weather("   ")


def test_weather_unknown_place(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(200, {"results": []}))
    with pytest.raises(weather.WeatherError, match="No Indian place"):
        weather.get_weather("Nowhereville")


def test_weather_outage_is_source_down(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(weather.requests, "get", boom)
    with pytest.raises(SourceDown, match="Weather service unavailable"):
        weather.get_weather("Ludhiana")


def test_mandi_missing_key(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "")
    with pytest.raises(mandi.MandiError, match="key is not set"):
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")


def test_mandi_reports_no_data_for_an_unknown_crop(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: FakeResponse(200, {"records": []}))
    with pytest.raises(mandi.MandiError, match="No Wheat market prices"):
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Wheat")


def test_mandi_error_message_never_contains_key(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "secret-key-123")
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: FakeResponse(502))
    with pytest.raises(SourceDown) as info:
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
    assert "secret-key-123" not in str(info.value)
    assert "HTTP 502" in str(info.value)


def test_mandi_no_rows_is_reported(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: FakeResponse(200, {"records": []}))
    with pytest.raises(mandi.MandiError, match="No Potato market prices"):
        mandi.get_mandi_prices("Manipur", "Imphal West", "Potato")


def test_mandi_rate_limit_is_source_down(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(
        mandi.requests, "get", lambda *a, **k: FakeResponse(200, {"error": "Rate limit exceeded"})
    )
    with pytest.raises(SourceDown, match="Rate limit exceeded"):
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")


def test_mandi_success_is_cached_then_served_as_hit(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    records = {"records": [{"market": "Khanna", "modal_price": 2000, "min_price": 1800,
                            "max_price": 2100, "arrival_date": "31/10/2026"}]}
    calls = []

    def live(*a, **k):
        calls.append(1)
        return FakeResponse(200, records)

    monkeypatch.setattr(mandi.requests, "get", live)
    first = mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
    second = mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
    assert first["rows"] and second["rows"]
    assert len(calls) == 1  # the second answer came from the saved rows, not the network
    assert second["stale"] is False
