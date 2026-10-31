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
app.py              FastAPI routes: /, /advise, /health
agent.py            Gemini function-calling loop and tool dispatch
safety.py           dosage removal, source list, warnings
tools/weather.py    Open-Meteo lookup and forecast
tools/mandi.py      data.gov.in mandi prices with retries
static/index.html   farmer page
tests/              unit tests for tools, safety, and the API
```

## Limits and honest gaps

- Mandi prices depend on an external service that is intermittently unavailable. The app shows an error rather than an old or made-up price.
- Coverage is not national. Only markets in the dataset appear, so some districts have no prices.
- Soil data is not included in this version. SoilGrids returned errors during testing.
- Voice input and output are not included yet. They are planned as a browser feature.
- Advice is general guidance. It does not replace a local agronomist, and chemical doses are always referred to a Krishi Vigyan Kendra.
