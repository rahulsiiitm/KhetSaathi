"""Deterministic field-risk rules computed from a daily forecast.

The model does not decide risk. These rules do, in plain code, and every risk carries
the rule ID, the threshold, and the forecast values that triggered it. The model can
explain a risk, but it cannot invent one, and the app shows the rule behind each risk.

Thresholds are conservative agronomy rules of thumb for field operations. They are not
crop-specific advice. Chemical and dosage advice is never generated here.
"""

HEAVY_RAIN_MM = 20.0  # daily rain at which field work and spraying are unsafe
SPRAY_RAIN_LIMIT_MM = 2.0  # rain above this washes off most sprays
HEAT_MAX_C = 35.0  # daily max at which crops show heat stress
COLD_MIN_C = 5.0  # daily min at which seedlings can be damaged
DRY_TOTAL_MM = 2.0  # total rain over the window below which the spell is dry
DRY_HOT_MAX_C = 30.0  # max temperature that makes a dry spell need irrigation


def assess(forecast: list[dict]) -> list[dict]:
    """Return the risks triggered by the forecast, most severe first."""
    risks = []

    for day in forecast:
        if day["rain_mm"] >= HEAVY_RAIN_MM:
            risks.append(_risk(
                "R1", "high", day["date"],
                f"Heavy rain of {day['rain_mm']} mm is forecast. Postpone field work and check drainage.",
                {"rain_mm": day["rain_mm"], "threshold_mm": HEAVY_RAIN_MM},
            ))
        if day["max_c"] >= HEAT_MAX_C:
            risks.append(_risk(
                "R2", "medium", day["date"],
                f"Heat stress: maximum of {day['max_c']} °C. Irrigate early in the morning.",
                {"max_c": day["max_c"], "threshold_c": HEAT_MAX_C},
            ))
        if day["min_c"] <= COLD_MIN_C:
            risks.append(_risk(
                "R3", "medium", day["date"],
                f"Cold stress: minimum of {day['min_c']} °C. Protect young plants from cold.",
                {"min_c": day["min_c"], "threshold_c": COLD_MIN_C},
            ))

    spray_days = [d["date"] for d in forecast if d["rain_mm"] < SPRAY_RAIN_LIMIT_MM]
    if spray_days:
        risks.append(_risk(
            "R4", "info", spray_days[0],
            f"Low rain on {', '.join(spray_days)}. These days suit field operations, if wind is calm.",
            {"days_below_rain_limit": spray_days, "limit_mm": SPRAY_RAIN_LIMIT_MM},
        ))

    total_rain = round(sum(d["rain_mm"] for d in forecast), 1)
    hottest = max((d["max_c"] for d in forecast), default=0)
    if forecast and total_rain < DRY_TOTAL_MM and hottest >= DRY_HOT_MAX_C:
        risks.append(_risk(
            "R5", "medium", forecast[0]["date"],
            f"Dry, warm spell: {total_rain} mm rain in {len(forecast)} days with temperatures up to "
            f"{hottest} °C. Plan irrigation.",
            {"total_rain_mm": total_rain, "hottest_c": hottest, "dry_limit_mm": DRY_TOTAL_MM},
        ))

    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(risks, key=lambda r: order[r["severity"]])


def _risk(rule: str, severity: str, date: str, message: str, inputs: dict) -> dict:
    return {"rule": rule, "severity": severity, "date": date, "message": message, "inputs": inputs}
