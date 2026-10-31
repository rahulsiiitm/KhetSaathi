import time

import pytest

import store
from tools import mandi, places


def _row(state, district, market, commodity, modal, synced_at=None):
    return {
        "state": state, "district": district, "market": market, "commodity": commodity,
        "variety": "", "grade": "", "arrival_date": "31/10/2026",
        "min_price": str(int(modal) - 100), "max_price": str(int(modal) + 100), "modal_price": modal,
    }


# ---- Local market data ----

def test_synced_rows_are_served_without_touching_the_network(monkeypatch):
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    store.save_mandi_rows([_row("Punjab", "Ludhiana", "Khanna APMC", "Potato", "1800")])
    result = mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
    assert result["rows"][0]["market"] == "Khanna APMC"
    assert result["rows"][0]["modal_price_per_quintal"] == "1800"
    assert result["source"].endswith("synced copy")
    assert result["stale"] is False


def test_old_synced_rows_are_marked_stale():
    store.save_mandi_rows([_row("Punjab", "Ludhiana", "Khanna APMC", "Potato", "1800")])
    # Pretend the rows were synced three days ago.
    import sqlite3
    with sqlite3.connect(store.DB_PATH) as conn:
        conn.execute("UPDATE mandi_rows SET synced_at = ?", (time.time() - 3 * 24 * 3600,))
    result = mandi.get_mandi_prices("Punjab", "Ludhiana", "Potato")
    assert result["stale"] is True
    assert result["age_hours"] >= 72


def test_crop_names_match_ignoring_case_and_list_includes_synced_crops():
    store.save_mandi_rows([_row("Punjab", "Ludhiana", "Khanna APMC", "Garlic", "9000")])
    assert mandi.match_crop("potato") == "Potato"
    assert mandi.match_crop("garlic") == "Garlic"
    assert "Garlic" in mandi.list_crops()
    assert "Wheat" in mandi.list_crops()  # seed crops are always offered


def test_district_without_rows_names_districts_that_have_data(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: type("R", (), {"status_code": 200, "json": lambda self: {"records": []}})())
    store.save_mandi_rows([_row("Punjab", "Ludhiana", "Khanna APMC", "Potato", "1800")])
    with pytest.raises(mandi.MandiError, match="Markets with data in Punjab include: Ludhiana"):
        mandi.get_mandi_prices("Punjab", "Patiala", "Potato")


def test_sync_stores_every_page_and_stops_at_the_total(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")
    pages = {0: [_row("Punjab", "Ludhiana", f"Market {i}", "Potato", "1000") for i in range(3)], 3: []}
    calls = []

    class Response:
        status_code = 200

        def __init__(self, offset):
            self.offset = offset

        def json(self):
            return {"total": 3, "records": pages.get(self.offset, [])}

    def fake_get(url, params=None, timeout=None):
        calls.append(params["offset"])
        return Response(params["offset"])

    monkeypatch.setattr(mandi.requests, "get", fake_get)
    assert mandi.sync_all() == 3
    assert calls == [0]  # total is 3, so one page is enough


def test_sync_reports_a_stopped_service_without_crashing(monkeypatch):
    monkeypatch.setenv("DATA_GOV_IN_KEY", "test-key")

    def down(*a, **k):
        raise mandi.requests.ConnectionError("unreachable")

    monkeypatch.setattr(mandi.requests, "get", down)
    with pytest.raises(mandi.SourceDown):
        mandi.sync_all()


# ---- Exact location ----

def test_coordinates_are_recognised_and_bad_ones_rejected():
    assert places.parse_coordinates("30.9010, 75.8573") == (30.901, 75.8573)
    assert places.parse_coordinates("Ludhiana") is None
    assert places.parse_coordinates("200,75") is None


def test_distance_between_two_known_points_is_about_right():
    # Ludhiana to Chandigarh is about 90 km in a straight line.
    assert 85 < places.distance_km(30.9010, 75.8573, 30.7333, 76.7794) < 95


def test_nearest_markets_are_sorted_by_distance_and_unlocatable_ones_are_left_out(monkeypatch):
    points = {"Near APMC": (30.92, 75.86), "Far APMC": (31.30, 75.50)}
    monkeypatch.setattr(places, "_geocode_market", lambda market, d, s: points.get(market))
    rows = [
        {"market": "Far APMC", "modal_price": "1700", "arrival_date": "31/10/2026"},
        {"market": "Near APMC", "modal_price": "1800", "arrival_date": "31/10/2026"},
        {"market": "Unknown APMC", "modal_price": "1600", "arrival_date": "31/10/2026"},
    ]
    result = places.nearest_markets(30.9010, 75.8573, "Punjab", "Ludhiana", rows)
    assert [m["market"] for m in result] == ["Near APMC", "Far APMC"]
    assert result[0]["distance_km"] < result[1]["distance_km"]
    assert result[0]["modal_price_per_quintal"] == "1800"


def test_weather_accepts_exact_coordinates(monkeypatch):
    from tools import weather
    place = weather.find_place("30.9010,75.8573")
    assert place["latitude"] == 30.901 and place["longitude"] == 75.8573
