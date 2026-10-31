from risk import COLD_MIN_C, HEAT_MAX_C, HEAVY_RAIN_MM, assess


def day(date, rain, t_max, t_min):
    return {"date": date, "rain_mm": rain, "max_c": t_max, "min_c": t_min}


def rules(risks):
    return {r["rule"] for r in risks}


def test_heavy_rain_triggers_r1_as_high_severity():
    risks = assess([day("2026-11-01", HEAVY_RAIN_MM + 5, 25, 12)])
    assert "R1" in rules(risks)
    high = [r for r in risks if r["rule"] == "R1"][0]
    assert high["severity"] == "high"
    assert high["inputs"]["threshold_mm"] == HEAVY_RAIN_MM


def test_heat_triggers_r2():
    assert "R2" in rules(assess([day("2026-11-01", 0, HEAT_MAX_C + 1, 20)]))


def test_cold_triggers_r3():
    assert "R3" in rules(assess([day("2026-11-01", 0, 20, COLD_MIN_C - 1)]))


def test_low_rain_days_give_spray_window_r4():
    risks = assess([day("2026-11-01", 0, 25, 12), day("2026-11-02", 0.5, 26, 13)])
    r4 = [r for r in risks if r["rule"] == "R4"][0]
    assert r4["inputs"]["days_below_rain_limit"] == ["2026-11-01", "2026-11-02"]


def test_dry_warm_spell_triggers_r5():
    forecast = [day("2026-11-01", 0, 32, 14), day("2026-11-02", 0.5, 31, 14)]
    assert "R5" in rules(assess(forecast))


def test_calm_mild_forecast_has_no_alarm_rules():
    risks = assess([day("2026-11-01", 5, 24, 12)])
    assert not rules(risks) & {"R1", "R2", "R3", "R5"}


def test_results_are_sorted_most_severe_first():
    risks = assess([day("2026-11-01", HEAVY_RAIN_MM + 1, HEAT_MAX_C + 1, 12)])
    severities = [r["severity"] for r in risks]
    assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1, "info": 2}[s])
