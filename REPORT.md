# Brighton Bikeshare — Analysis, Forecasting & Conclusions

Source: live GBFS feed from Beryl (Brighton), pulled by the ETL pipeline in `utils.py` (wired up by the single app file `app.py`).
Data so far: 119 stations observed across repeated snapshots, logged to `data/history.csv` on every page load.

This report deliberately moves past the numbers (counts, percentages, ranks) and asks what the data is telling us, what we should predict, and what we should do about it.

---

## 1. What the live data actually tells us

### 1.1 The network is a pulse, not a snapshot
A single station-status fetch is a photograph. What makes bikeshare interesting is the *rhythm*: bikes flood out of residential station clusters in the morning, pool at the station, drift to the parks and the seafront on weekends, and slosh back in the evening. A one-off count tells you little; the *shape over time* tells you a lot. This is the single most important reframe: stop reading levels, start reading flows.

### 1.2 Availability is a rebalancing problem, not a demand problem
When we see a station empty (0 bikes) or full (0 docks), the instinct is "demand is high here." More accurately: the operator's rebalancing truck hasn't moved bikes back yet. Empty ≠ unpopular. Empty frequently means *so* popular that bikes leave faster than they return. These are the stations where the failure mode is a locked-out rider, not a lost sale.

### 1.3 Extreme percentages flag friction, not just utilisation
A station pinned at ~0% or ~100% utilisation across the whole observation window is a station that is chronically mis-priced by its capacity. The interesting analytics target is not the average utilisation — it's the stations that swing hard, because swings are where riders get burned.

### 1.4 The real metrics
Two things deserve attention that a first-glance dashboard hides:
- **Station failure rate over time** — how often a given station crosses into empty/full. This is a reliability metric, far more actionable than a mean.
- **Rebalance necessity** — stations that alternate quickly between empty and full are the ones costing the operator money and riders time.

---

## 2. What we should forecast

Not "how many bikes." Questions worth predicting, in order of value:

### 2.1 Which stations will fail (be empty/full) in the next 30–60 minutes?
This is the headline prediction. It tells riders where to find a bike/dock now, and it tells operations which trip to rebalance next. It is a classification task (empty / full / available), not a regression.

### 2.2 How many bikes will be at each station at the next checkpoint?
The lower-precision cousin — but it feeds the failure forecast as a feature, and it powers rider-facing "likely available" hints.

### 2.3 Recency-adjusted demand
Forecast *arrivals* and *departures* per station per time-step, then convert to net. This is what a rebalancing scheduler actually needs. Predicting net level alone loses the churn (bikes may leave and return in the same window).

### 2.4 Demand by weather, events and time of day
Brighton is a coastal leisure city: weather and fixture/event days will move the seafront and stadium clusters dramatically. These are *drivers* to feed the model, not outcomes to forecast directly.

---

## 3. How to forecast it (practical approach)

Start cheap, get a baseline, then add complexity only where it measurably helps.

### Stage 1 — Persistence baseline (do this first, seriously)
The simplest defensible forecast: "next value = current value." For 30–60 min horizons on bikeshare, this is often surprisingly good and is the number you must beat. Everything below is measured against it.

### Stage 2 — Time-of-day + day-of-week profile
Per station, build the historical average curve for each day-of-week × hour-of-day. Forecast = seasonal profile, naive on the last observed drift. This captures the rhythm with almost no machinery (a grouped mean). Expect this to beat persistence at stations with strong commuting or weekend rhythms.

### Stage 3 — Lightweight ML (once history is big enough)
Once history.csv holds several thousand rows per station pulse:
- **Model:** LightGBM or a small gradient-boosted tree per-station (or per cluster of similar stations), predicting bikes/docks at horizon *h* from lag features (last 2–4 readings), hour, weekday, weather, event flag.
- **Alternative:** a simple SARIMA or Prophet per station as a saner-time-series counterpart; trees usually win on heteroscedastic, eventful data.
- **Failure model:** logistic/boosted classifier on "will be empty/full in 60 min" — threshold is a business decision, tuned on false-lockouts (rider harm) vs. false-alarm cost.

### Stage 4 — Operational layer
The forecast only matters if it changes an action:
- Rebalance trigger: predict departures minus arrivals per station; dispatch when a station is projected to fail.
- Rider surface: give "likely empty in the next hour" flags in the UI, with a confidence score, not a raw count.

### Data hygiene that must come first
History only accumulates while the page is open. **Before any serious modelling, add a background collector** (`app.py --collect` + cron every 5 min) so you have continuous, gap-free, timestamped series. Also record the *driver* variables (weather, events, temperature, rain) in the same pipeline — you cannot backfill weather-for-learning later by guessing. And normalise station_id consistently (we already hit the int-vs-str mismatch once) — a forecasting pipeline will silently die on a type drift.

---

## 4. Conclusions & recommendations

### 4.1 Summary of findings
- The network is large (119 stations) and live-feed well-served, but a single snapshot is observationally thin — value grows quickly with continuous collection.
- The most decision-relevant signal is the empty/full *failure* of stations, driven by rebalancing lag as much as by demand.
- Qualitative insight beats raw counts: focus on flows, rhythms and reliability, not averages.

### 4.2 Actions that follow
1. **Switch collection to a scheduled collector now** — the highest-leverage non-code change. Unbroken history is the prerequisite for every forecast above.
2. **Instrument driver data (weather, events, weekend flags) from day one** — cheap to add, impossible to reconstruct accurately later.
3. **Ship flow-based views** (bikes-in vs bikes-out per station over time) before any ML — they'll answer most operational questions directly and clarify whether a forecast is even needed.
4. **Adopt the persistence baseline as the "good enough" bar** for a first rider-facing hint; only invest in Stage-3 models once history is thick enough to beat it.
5. **Model failure, not levels** — the empty/full classification forecast has the clearest business payoff (rider trust + rebalance efficiency).
6. **Treat 30–60 minute horizons as the sweet spot** — long enough to act on, short enough that persistence is a weak competitor.

### 4.3 The one-sentence takeaway
Stop asking "how many bikes are here right now?" and start asking "which stations are about to fail, and why" — then run a scheduled collector and let time turn the dashboard's photographs into a movie you can actually steer an operator's decisions from.

---

## Appendix — how to wire it up
- Collector: `uv run app.py --collect`, which calls the same `extract/transform/load` helpers in `utils.py`, run via cron / Windows Task Scheduler every 5 minutes, writing to `history.csv` server-side (not per-page-view).
- Forecast sketch: `h = 60 min`, features = last 4 readings, hour, weekday, temp, rain, event flag; model = LightGBM; metric = accuracy + weighted false-lockout cost for the failure classifier.
- Keep units stable: bikes and docks as integers; timestamps as UTC ISO; `station_id` as string everywhere.