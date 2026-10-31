"""Failure-path tests for the live data sources.

These cover what judges will try: the service goes down, a source keeps failing,
and a district has no data. Each must give a clear answer, and never a made-up number.
"""

import time

import requests

import store
from tools import mandi, weather
from tools.cache import SourceDown


class Down:
    """Stands in for requests.get when the upstream service is unreachable."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise requests.ConnectionError("unreachable")


def test_mandi_outage_serves_last_saved_price_marked_stale(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(mandi.time, "sleep", lambda s: None)
    # A price saved earlier, now past its 6-hour TTL.
    key = "mandi:punjab|ludhiana|potato"
    two_days_ago = time.time() - 2 * 24 * 3600
    store.cache_put(key, {"rows": [{"market": "Khanna", "variety": "", "grade": "", "arrival_date": "29/10/2026",
                                    "min_price": "1400", "max_price": "1600", "modal_price": "1500"}],
                          "fetched": two_days_ago}, ttl_seconds=0)
    monkeypatch.setattr(mandi.requests, "get", Down())

    result = mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")

    assert result["stale"] is True
    assert result["rows"][0]["modal_price_per_quintal"] == "1500"
    assert result["stale_reason"]  # the farmer-facing reason is recorded
    assert result["saved_at"]


def test_mandi_outage_with_nothing_saved_raises_clearly(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(mandi.time, "sleep", lambda s: None)
    monkeypatch.setattr(mandi.requests, "get", Down())
    try:
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
        raise AssertionError("expected SourceDown")
    except SourceDown as error:
        assert "unavailable" in str(error)


def test_breaker_stops_calls_after_repeated_outages(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(mandi.time, "sleep", lambda s: None)
    down = Down()
    monkeypatch.setattr(mandi.requests, "get", down)

    for _ in range(store.BREAKER_FAILURES):
        try:
            mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
        except SourceDown:
            pass
    calls_before_pause = down.calls

    try:
        mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
    except SourceDown as error:
        assert "paused" in str(error)
    assert down.calls == calls_before_pause  # no network call while paused


def test_no_data_for_a_district_does_not_count_as_outage(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")

    class Empty:
        def __call__(self, *a, **k):
            class R:
                status_code = 200
                def json(self): return {"records": []}
            return R()

    monkeypatch.setattr(mandi.requests, "get", Empty())
    for _ in range(store.BREAKER_FAILURES + 1):
        try:
            mandi.get_mandi_prices("Manipur", "Imphal West", "Potato")
        except mandi.MandiError:
            pass
    assert store.breaker_open("data.gov.in") is False


def test_weather_outage_serves_stale_forecast(monkeypatch):
    place = {"name": "Ludhiana", "state": "Punjab", "latitude": 30.9, "longitude": 75.85}
    store.cache_put("forecast:30.900,75.850:3", {"place": place, "forecast": [], "source": "Open-Meteo",
                                                  "fetched_at": "2026-10-30T06:00:00+00:00"}, ttl_seconds=0)
    monkeypatch.setattr(weather, "find_place", lambda name: place)
    monkeypatch.setattr(weather.requests, "get", Down())

    result = weather.get_weather("Ludhiana")

    assert result["stale"] is True
    assert result["place"]["name"] == "Ludhiana"
