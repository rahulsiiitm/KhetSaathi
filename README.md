# KhetSaathi

A voice-ready advisory assistant for Indian farmers. It combines live weather, live mandi (market) prices, and a Gemini agent that decides which tools to call. Every answer shows the sources and fetch times it used, and it says plainly when data is missing.

Track: Theme 2 (Climate, Resource Infrastructure & Global Supply Resilience), Problem 1.

## Architecture

```
Farmer (browser: static/index.html)
   |  POST /advise  (question, place, state, crop)
   v
FastAPI (app.py)  --validates input-->  agent.py
                                          |
                     Gemini chat with automatic tool calls (max 4)
                       |                          |
               get_weather(place)        get_mandi_prices(state, district, crop)
                       |                          |
          tools/weather.py                tools/mandi.py
          Open-Meteo (live, no key)       data.gov.in Agmarknet (live, key needed)
                       \                          /
                        results -> back to Gemini
                                          |
                                     safety.py
                          remove dosage lines, list sources, add warnings
                                          |
                                  advice + sources + trace
```

**Agent loop (agent.py):** the model receives the farmer's question and two Python tool functions. The Gemini SDK runs the tool calls automatically, up to 4, and sends each result back. Tool errors are returned to the model as data, so it must report missing information instead of guessing. The final text is checked by `safety.py`. The reply language follows the question: Hindi if it contains Devanagari, otherwise English.

**Guardrails (safety.py):** chemical dosage lines are removed in code, not just by prompt. Sources are built from successful tool results only, so the model cannot cite data it did not fetch.

## Data sources

| Data | Source | Key needed | Notes |
|---|---|---|---|
| Weather forecast | [Open-Meteo](https://open-meteo.com/) forecast and geocoding APIs | No | Works for any Indian village or town |
| Mandi prices | [data.gov.in](https://data.gov.in), Agmarknet "Current Daily Price of Various Commodities from Various Markets (Mandi)" | Yes, free | Prices are per market. Some districts, including Imphal (Manipur) in this dataset, have no rows. The app says so. The service is intermittently unavailable. |

## Setup

Requires Python 3.11 or newer.

```bash
cd KhetSaathi
python -m pip install -r requirements.txt
cp .env.example .env          # then fill in your keys
```

Fill in `.env`:

```
GEMINI_API_KEY=...       # Google AI Studio: https://aistudio.google.com/app/apikey
GEMINI_MODEL=gemini-3.1-flash-lite   # tested with this model; check your key's model list if it changes
DATA_GOV_IN_KEY=...      # data.gov.in account area
```

Run the app:

```bash
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000. Check the server with http://127.0.0.1:8000/health.

Run the tests:

```bash
python -m pytest -q
```

## Project layout

```
app.py              FastAPI routes: /, /advise, /health, /status
agent.py            Gemini chat with three tools, the reply-language rule, and tool dispatch
risk.py             fixed rules R1 to R5 on the forecast (heavy rain, heat, cold, spray window, dry spell)
safety.py           dosage removal, figure-grounding check, source list, freshness labels
store.py            SQLite: TTL cache, source health, circuit breaker state, advice log
tools/cache.py      one path for every live call: cache, circuit breaker, stale fallback
tools/weather.py    Open-Meteo lookup and forecast (forecast cached 30 min, place lookup 30 days)
tools/mandi.py      data.gov.in mandi prices (cached 6 hours)
static/index.html   farmer page with voice input and read-aloud
tests/              39 tests: cache and breaker, risk rules, tools, safety, and API
```

**Data flow for one question:** the page posts the question to `/advise`. The agent calls the weather, risk, and mandi tools as the model needs them. Each tool goes through `tools/cache.py`, which serves a fresh cache entry if one exists, skips a source the circuit breaker has paused, or fetches live and saves the result. If the live fetch fails, the last saved result is returned and labeled stale. The risk rules run in code on the forecast. The model explains them but cannot add risks. `safety.py` then removes dosage lines, flags any figure with a unit that no tool returned, and lists the sources with their freshness. The answer and its latency are logged in SQLite.

**Operations:** `GET /status` reports each data source (last success, last error, failures in a row, paused or not), cache size, and the number of answers served with average latency. After three failures in a row, a source is paused for 10 minutes.

## Limits and honest gaps

- Mandi prices depend on an external service that is intermittently unavailable. The app serves the last saved price, labeled stale with its fetch time. If nothing was ever saved, it says the prices are unavailable.
- Coverage is not national. Only markets in the dataset appear, so some districts have no prices.
- Soil data is not included in this version. SoilGrids returned errors during testing.
- Voice input and output are not included yet. They are planned as a browser feature.
- Advice is general guidance. It does not replace a local agronomist, and chemical doses are always referred to a Krishi Vigyan Kendra.
