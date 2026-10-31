# KhetSaathi: 5–7 slide deck outline and 2–3 minute demo script

## Deck (7 slides)

1. **Title and team**
   KhetSaathi: live weather and market advice for farmers, in Hindi and English.
   Track: Theme 2, Problem 1 (Multilingual Agritech and Resource Advisory Assistant).

2. **The problem**
   Farmers decide when to spray, irrigate, and sell with weather, market, and soil information spread across sources, mostly in English. One late decision costs a crop or a price.
   Fill in one real number for the audience (for example, a local crop loss or price swing) from a source you can cite.

3. **The solution**
   A voice-enabled assistant. A farmer speaks or types a question in Hindi or English. An AI agent fetches live weather and mandi prices, then answers with a dated plan, the data it used, and what it could not get.

4. **Architecture and innovation**
   Diagram from the README: browser, FastAPI, Gemini agent with two live tools, guardrails, sources list.
   Innovation to name: guardrails in code (dosage lines removed; every figure must match fetched data; stale prices labeled), not only in the prompt.

5. **Reliability**
   Show what happens when a service fails: the answer says the data is unavailable, or shows the last saved price marked as stale. Never an invented number.

6. **Roadmap**
   Soil data (SoilGrids is in the plan but was unavailable during build), more crops and states, SMS and IVR for farmers without smartphones, advisor dashboards.

7. **Live demo summary**
   Link to the live app. Three things to watch in the demo: a spoken question, the cited answer, and a failure case.

## Demo script (2–3 minutes, label any recording clearly)

1. (0:00) Open the live URL on a phone. Say the problem in one sentence.
2. (0:20) Tap "Speak question", ask in Hindi: "मेरी आलू की फसल पर अभी स्प्रे करना सही है?" Show the transcript.
3. (0:50) Submit with Ludhiana, Punjab, Potato. Point out the tool calls in "How this was worked out".
4. (1:20) Read the answer: decision, day-by-day plan, "Based on" data, sources with fetch times.
5. (1:45) Tap "Read aloud" and let the Hindi answer play.
6. (2:00) Failure case: enter an unknown place, or show a stale price warning. Explain that the app refuses to invent a number.
7. (2:30) Close: the guardrails, the live sources, and the next step (SMS for farmers without smartphones).

## Before recording

- Confirm the live URL works on a phone that is not your development machine.
- Test the microphone and the Hindi voice on the same phone.
- If the price service is down during the demo, the stale-price path is the honest fallback. Show it.
