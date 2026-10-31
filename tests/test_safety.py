from safety import check_answer, remove_dosages


def test_dosage_line_is_removed():
    text = "Spray in the morning.\nUse 2 ml per litre of water.\nIrrigate on Friday."
    cleaned, changed = remove_dosages(text)
    assert changed is True
    assert "2 ml" not in cleaned
    assert "Spray in the morning." in cleaned
    assert "Irrigate on Friday." in cleaned


def test_plain_advice_is_untouched():
    text = "Rain is expected on Tuesday, so delay spraying."
    cleaned, changed = remove_dosages(text)
    assert changed is False
    assert cleaned == text


def test_sources_come_from_successful_tools_only():
    trace = [
        {
            "tool": "get_weather",
            "args": {"place": "Ludhiana"},
            "result": {
                "place": {"name": "Ludhiana", "state": "Punjab"},
                "source": "Open-Meteo",
                "fetched_at": "2026-10-31T06:00:00+00:00",
                "forecast": [],
            },
        },
        {"tool": "get_mandi_prices", "args": {}, "result": {"error": "service down"}},
    ]
    result = check_answer("Delay spraying.", trace)
    assert any("Open-Meteo" in s for s in result["sources"])
    assert not any("Mandi" in s for s in result["sources"])
    assert any("Mandi prices could not be fetched" in w for w in result["warnings"])
    assert not any("get_mandi_prices" in w for w in result["warnings"])  # no raw tool names for farmers


def _weather_trace():
    return [
        {
            "tool": "get_weather",
            "args": {"place": "Ludhiana"},
            "result": {
                "place": {"name": "Ludhiana", "state": "Punjab"},
                "source": "Open-Meteo",
                "fetched_at": "2026-10-31T06:00:00+00:00",
                "forecast": [{"date": "2026-11-01", "rain_mm": 0.0, "max_c": 29.0, "min_c": 17.1}],
            },
        }
    ]


def test_grounded_figures_pass():
    result = check_answer("Expect 0.0 mm rain and a high of 29.0 °C tomorrow.", _weather_trace())
    assert not any("could not be matched" in w for w in result["warnings"])


def test_invented_figure_is_flagged():
    result = check_answer("Expect 45 mm of rain tomorrow.", _weather_trace())
    assert any("45 mm" in w for w in result["warnings"])


def test_stale_mandi_is_labeled():
    trace = [
        {
            "tool": "get_mandi_prices",
            "args": {},
            "result": {
                "commodity": "Potato", "district": "Ludhiana", "state": "Punjab",
                "source": "data.gov.in (Agmarknet)", "fetched_at": "2026-10-30T06:00:00+00:00",
                "stale": True, "rows": [],
            },
        }
    ]
    result = check_answer("General tip.", trace)
    assert any("STALE" in s for s in result["sources"])
    assert any("earlier fetch" in w for w in result["warnings"])


def test_no_live_data_adds_warning():
    result = check_answer("General tip.", [])
    assert result["sources"] == []
    assert any("No live data" in w for w in result["warnings"])
