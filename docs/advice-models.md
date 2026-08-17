# Window advice models (v1 / v2)

Settings → **Window advice** chooses which model drives the top-bar banner,
Map airflow arrows, window notifications, and Map **Ask Cursor**. The choice
is stored in this browser (`localStorage` key `govee-charts.adviceModel`).
Default is **v1**. Compare chart **Window open / close** bands always use v1.

Both models answer the same question: *should we open windows to cool, or
keep heat out?* They disagree on **which outdoor air** to trust, **how large
a ΔT is worth acting on**, and **what to do when the AC is running**.

## v1 — weather station vs indoor air

v1 is the original behaviour. It treats “outside” as a **single number**:
the configured weather station (Open-Meteo / GPS place), not the air at the
apartment façades.

It is implemented in two places that do not share a function:

| Surface | Where | Outdoor input | Indoor input | Act if |
|---|---|---|---|---|
| Banner, notifications, chart bands | `static/app.js` (`windowAdviceKind`, `WINDOW_DELTA_C = 0.5`) | Station temperature now | One interior device per room | \|ΔT\| ≥ **0.5 °C** |
| Map through-draft | `suggest_cooling_airflow` | Same station temperature | Mean of live room temps | Hold if outdoor ≥ indoor − **0.3 °C** |

### Banner / notifications (JS)

For each interior room that has a door/window contact:

1. `Δ = T_indoor − T_station`.
2. `Δ ≤ −0.5 °C` → **close** (outside warmer).
3. `Δ ≥ +0.5 °C` → **open**, unless outdoor dew point is within **0.5 °C** of indoor air (**humid** — cooler but too wet).
4. Otherwise **near balance** (no strong action).

The banner then crosses that kind with live contact state (already open vs
still closed) to produce “open now / close now / OK open / OK closed”.

### Map airflow (Python)

If the station is not clearly cooler than the **apartment-wide indoor
average** (margin 0.3 °C), mode is **hold**: keep windows closed, no inlet
path.

Otherwise it scores façade rooms (windward inlet, leeward / hot chimney
outlet, opposing orientations) and proposes a through-flow on the door
graph. Closed doors may still sit on the path, listed as “open this door”.

Façade Govee sensors (`zone = exterior`) are **not** used for the go/no-go
decision. HVAC being on is **not** used either (the Map may still badge the
AC room while suggesting a draft).

### Why v1 misfires here

The station is a neighbourhood proxy. A south wall in the sun, or an
extractor blowing indoor air onto an “exterior” probe, can be several
degrees away from that proxy. A 0.3–0.5 °C threshold also fires on sensor
noise. Opening windows while the bedroom AC is on fights the machine.

## v2 — air at the window, then isolate AC

v2 keeps v1 as a **path finder** only. The **decision** is new:
`advise_climate_v2` / `suggest_cooling_airflow_v2`.

Principle: compare indoor air to the air that would **actually enter that
room’s window**, require a **useful** ΔT, treat a façade probe that looks
like **exhaust** as untrusted, and if the AC is on **stop ventilating**
(isolate that room) instead of drawing a through-draft.

### 1. Air at the window (`room_window_air_c`)

Per room with an exterior orientation:

1. Average live **exterior-zone** sensors on that room.
2. **Plume:** drop a probe that sits within **0.6 °C** of indoor air while
   the station is at least **1.5 °C** cooler than indoors. If every façade
   probe is dropped, fall back to the station (`window_source = plume_fallback`).
3. Else use `facade_temp_c` if present, else the station.

So when a façade disagrees with the station, the façade wins — unless it
looks like indoor air leaking onto the probe.

### 2. Per-room kind (`advice_kind_v2`)

Same open / close / humid / balance shape as v1, but:

- outdoor side is **window air**, not the station;
- threshold is **1.5 °C** (`ADVICE_V2_DELTA_C`);
- dew point still uses **station** temperature + humidity (RH is not
  measured at the glass).

### 3. HVAC isolate

If HVAC is **active**, every room that would have been **open** is forced
to **close**. Mode becomes `hvac_isolate`: close the AC-room door if it is
open, keep its windows closed, **no cooling inlet**. Mechanical cooling
wins over night purge.

### 4. Through-draft only after that

If mode is not `cooling` (including isolate), airflow is **hold**.

If some façades are still worth opening, those rooms stay on the graph and
the others have their `exterior` stripped so v1 `suggest_cooling_airflow`
cannot pick a hot wall as inlet. The outdoor temperature passed into v1 is
the **coolest trusted window air**, not the station.

### API and UI

`GET /api/apartment` always returns both:

- `airflow` — v1 (unchanged);
- `airflow_v2` + `window_advice_v2` — v2.

The browser picks which payload to show. Map chat sends `advice_model`
so the agent prompt uses the matching snapshot and preamble (v2: prefer
façades, ignore plumes, isolate AC).

## Quick contrast

| | v1 | v2 |
|---|---|---|
| Outdoor air | Weather station | Façade / window air, station as fallback |
| ΔT to act | 0.5 °C (banner), 0.3 °C (Map hold) | 1.5 °C |
| Exhaust plume | Trusted like outdoor | Ignored if it matches indoor while station is cooler |
| AC on | Ignored for open/close | Isolate: no draft, close AC-room door |
| Chart history bands | Yes | Unchanged (still v1) |
