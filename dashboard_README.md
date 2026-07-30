# Joinville Meteo Dashboard — update bundle

Free, auto-updating, scientifically-rigorous meteorological dashboard for **Joinville (SC)**,
published on GitHub Pages. Static site (HTML/CSS/vanilla-JS SVG) fed by small JSON/CSV/GeoJSON files
that Python scripts build from the station network + public model data. **Standing rule: nothing is
invented — every value traces to a measurement, a peer-reviewed method, or real mathematics; known
limitations are declared, not masked.**

This folder is the working copy of everything produced with Claude (Cowork). The live repo is
elsewhere; apply these files there using `COMMIT_PLAN.md` (branch-per-feature). Then run
`python scripts/rain_qc.py` once (see below).

---

## Start here — documentation & reproducibility

- **`notebooks/Joinville_dashboard_pipeline.ipynb`** — the **exhaustive, plain-language +
  scientifically-cited walkthrough of the whole pipeline** (raw → QC → per-page data → WRF → publish),
  with runnable cells that re-derive every key diagnostic and embedded outputs. **Read this first** to
  understand, repeat, replicate and reproduce the dashboard.
- `README.md` (this file) — the bundle map and how to apply.
- `METODOLOGIA_DADOS.md` — per-page methodology in detail.
- `logs/Joinville_dashboard_forecast_log.md` — dated decision log.
- `notebooks/joinville_meteo_consolidation.ipynb` — ingestion/consolidation detail;
  `notebooks/CPTEC_WRF_Joinville_downloader.ipynb` — WRF download.
- `site/sobre.html` is the same methodology rendered for the public.

## What changed (this work, newest first)

0c. **Multi-hazard risk alerts + heat index, observed & forecast.** The Previsão and Agora alerts now
   cover **rain (OMM), wind (Beaufort, WMO-No. 306), temperature (provisional bands) and a heat index /
   "sensação"** (apparent temperature from temp × humidity; Steadman 1979 / NWS Rothfusz 1990; Atenção
   ≥ 32, Alerta ≥ 41 °C aparente). This added **2 m relative humidity** to the WRF pipeline
   (`fetch_wrf.py` → `rh2_pct`; `build_wrf_basins.py` → `vars.humid`/`has.humid`), graceful if the
   product lacks RH. Also: **"Acumulado" = next-24 h** rain total (matching the Evolução chart); hourly
   axes labelled in **local time**; the WRF grid archive is **year-chunked** (`site/data/wrf_archive/`)
   with a **Zenodo DOI**; and Sobre gained **"Como citar"** and **"Alertas de risco"** sections. All
   alerts are **"fase de teste."** Methodology + citations: `METODOLOGIA_DADOS.md`, `DATA_ARCHIVE.md`,
   `site/sobre.html`.

0aa. **Forecast rain-risk alert on the Previsão page** (`site/previsao.html`). A small box at the top
   applies the **same OMM/WMO intensity logic as the Agora alert** — but to the forecast: it takes the
   worst predicted hourly rain in some bairro over the run and shows Normal / Atenção / Alerta (alert at
   **forte, ≥10 mm/h**), clearly labelled **"Fase de teste"** with a disclaimer that it's direct WRF
   output, not an official Defesa Civil warning.

0a. **Ciência Cidadã (citizen-science) page** (`site/ciencia_cidada.html`). Plain-language page where a
   resident picks their **bairro**, sees **what the WRF forecast says for that bairro right now**, and
   answers whether it's raining and how hard — turning residents into ground-truth sensors that validate
   and correct the forecast. Responses flow **Google Form → Google Sheet → CSV in the repo**
   (`site/data/ciencia_cidada.csv`) via `.github/workflows/citizen-science-sync.yml`; a static site
   can't save a file itself, so this free collector is the bridge. **Setup (once, ~15 min):** follow
   **`CIENCIA_CIDADA_SETUP.md`** (create the Form, embed it, publish the Sheet as CSV, set one repo
   variable). The nav link was added to every page; footer carries the project + `jessica.jcss@gmail.com`.

0b. **Cumulative WRF grid archive** (`scripts/archive_wrf_grid.py` → `site/data/wrf_grid_archive.csv`).
   The per-run WRF files are overwritten daily; this **appends** each run's native-resolution (~7 km)
   per-cell hourly values (Joinville window) to one growing long CSV — append-only + idempotent
   (keyed by run + valid time + cell) — so the model history is retrievable later. Wired into
   `forecast-wrf.yml`; a download link is on the Previsão page.

1. **Whole-dashboard scientific-validity audit.** Every page was checked so text/captions/tables/figures
   match the actual data. Fixes:
   - **Wind rose (Agora)** — was faking a "North/South" peak from a *stuck/absent wind vane* (two
     stations reported direction exactly 0° for ~41 % of *windy* hours; one recent station 76.5 %).
     New QC in `build_site_data.py`: calm winds (< 0.5 m/s) are excluded and reported as a **calm %**;
     **broken-vane stations are dropped** (> 25 % of windy hours pinned to 0°). The rose now shows the
     physically sensible **East quadrant** (Atlantic sea breeze); the page states calm % and how many
     valid vanes remain. Wind text on Cidade updated to match.
   - **Cidade · Temp × Chuva** — four captions said rain came from the Defesa Civil gauges *alone*;
     corrected to the actual **blend of gauges + meteo stations**.
   - **Agora legend** "online (hoje)" → "online (leitura recente)" (freshness is an 8-day window).
   - **Chuva–Rio** — the QC-method line now states the full rule (median ± the *greater* of 6·MADn and
     the physical span −2.8/+3.5 m), which is the term that actually bound every station.
   - **Risco** — the "Situação" filter now includes the "Não informado" category present in the data.
   - Estação page: verified clean (no change needed).

2. **Rain quality control — inch-code sentinel + physical ceiling + catch-up dumps** (`scripts/rain_qc.py`).
   The tipping buckets are inch-based (tip 0.254 mm = 0.01 in); the logger fault code shows up as an
   *exact inch value* — **254.0 mm = 10 in appears 1,092×** (99.9th *and* 99.99th percentiles both
   exactly 254.0 — a sentinel, not weather), **228.6 mm = 9 in** 6×. Plus gross spikes (1606.8,
   961.8 mm/h) and catch-up dumps (big value right after a multi-hour gap). The rule **flags, never
   silently deletes**: `inch_code` {254.0, 228.6}; `ceiling` > 150 mm/h or 350 mm/day; `gap_dump`
   (≥40 mm after a >2 h gap). Flagged → **NaN (not 0)**. Runs at the end of `build_hourly_daily.py`
   and `update_datasets.py`, so **every** rain product is corrected. Audit trail:
   `data/processed/rain_qc_flags.csv` (1,236 points, ~0.14 %). Effect: ~20,500 mm of spurious rain
   removed across 41 station-months (e.g. udesc May 2025 1,721 → 114 mm); city annual now
   2,052–2,056 mm vs ~2,130 mm reference.

3. **WRF forecast — timezone & figure fixes.** Previsão times are now **Joinville local (UTC−3)** on
   every surface; the model **run cycle keeps its UTC label** (00Z/12Z), stated explicitly. Regional
   6-panel figure shows faint **SC + Joinville** outlines (real IBGE boundaries via
   `build_states_overlay.py`) and uses a **true geographic aspect** (no more flattening).
   `wrf_grid.geojson` coords rounded to 3 decimals (2.39 → 1.83 MB).

4. **WRF forecast page** (`site/previsao.html`, `scripts/build_wrf_basins.py`, `fetch_wrf.py`,
   `.github/workflows/forecast-wrf.yml`). CPTEC/INPE WRF (AMS 7 km) → rain / 2-m temp / 10-m wind by
   **basin and neighbourhood** (exact grid-cell ∩ polygon area weighting, EPSG:31982), regional
   patchwork figure, downloads, daily auto-fetch. Rain de-accumulated; temp/wind never differenced.

5. **ENSO overlay** (`scripts/build_enso.py`) — intensity-graded El Niño / La Niña bands on the daily
   analysis, ONI pulled live from NOAA/CPC (5-season rule), auto-refreshed.

6. **River-stage reframing + robust QC** — stage/cota vs datum (not water depth), Iate Clube estuary
   station, min→max heatmap, MAD-based window with physical span.

## How to apply

1. Copy files into your repo working tree.
2. Follow `COMMIT_PLAN.md` — one branch per feature.
3. **Run once:** `python scripts/rain_qc.py` — cleans the `prec` column of your hourly + daily station
   masters *in place* (only flagged cells change; everything else byte-identical) and writes the audit
   report. Idempotent, and already wired into CI so it stays clean.
4. Rebuild the affected site data (`build_site_data.py`, `build_station_history.py`,
   `build_gauges_city.py`, `build_city_history.py`, `build_river.py`, `build_disasters.py`) — or just
   let the weekly Action do it. Commit + push. The repo is **public**, so GitHub Actions minutes are
   **unlimited** (the four workflows total ~270–300 Linux-min/month — irrelevant on a public repo).

## Files

```
scripts/
  rain_qc.py               NEW  rain QC (inch-code / ceiling / gap-dump), audit trail
  build_states_overlay.py  NEW  SC/PR/SP outlines (IBGE) for the regional figure
  build_wrf_basins.py      WRF → basins/bairros/grid + regional figure (tz, overlay, aspect)
  fetch_wrf.py             NEW  headless CPTEC-WRF downloader (CI)
  build_enso.py            NEW  NOAA ONI → ENSO classification
  build_site_data.py       MOD  wind-rose QC (calm + broken-vane exclusion)
  build_river.py           MOD  QC-method text = median ± max(6·MADn, physical span)
  build_disasters.py       MOD  "Não informado" situação included
  archive_wrf_grid.py      NEW  append each WRF run to the cumulative grid archive CSV
  build_hourly_daily.py / update_datasets.py   MOD  call rain_qc at the end
  build_station_history.py / build_gauges_city.py / build_city_history.py / make_standalone_rio.py
notebooks/
  Joinville_dashboard_pipeline.ipynb        NEW  exhaustive reproducible end-to-end pipeline (start here)
  joinville_meteo_consolidation.ipynb            ingestion/consolidation detail
  CPTEC_WRF_Joinville_downloader.ipynb           consolidated rain+temp+wind WRF downloader
site/*.html                index, cidade, cidade_tempchuva, estacao, rio, risco, previsao, ciencia_cidada, sobre
CIENCIA_CIDADA_SETUP.md    step-by-step to wire the citizen-science Google Form → repo CSV
.github/workflows/citizen-science-sync.yml   Google Sheet responses → site/data/ciencia_cidada.csv
site/data/…                regenerated outputs (snapshot, city_history, station_history, river,
                           disasters, enso, wrf_*)
data/processed/rain_qc_flags.csv   audit trail — every removed rain point
.github/workflows/forecast-wrf.yml (daily) · update-data.yml (adds ENSO)
COMMIT_PLAN.md · METODOLOGIA_DADOS.md · logs/Joinville_dashboard_forecast_log.md
```

Not duplicated here: the heavy station **masters** (`data/hourly`, `data/daily`) — they are your own
data and live in the main project; `rain_qc.py` corrects them in place.

## Notes answered along the way

- **All displayed/output data is local time (UTC−3)**; only the WRF *run cycle* and the *build
  timestamp* are labelled UTC.
- **GeoJSON/CSV outputs are overwritten each run** (the live site always holds one copy). Git history
  keeps versions, but the WRF grid geometry is identical run-to-run so deltas are tiny. WRF CSVs are
  snapshots (not cumulative; `accum_mm` is cumulative only within a run's lead-time).
- **GitHub Actions:** public repo → unlimited. Daily WRF commit uses `[skip ci]` and keeps the repo
  active (avoids the 60-day auto-disable of scheduled workflows).

*Built with Claude (Cowork), 2026-07. LaCiA · PPGEC · UDESC–CCT, Joinville.*
