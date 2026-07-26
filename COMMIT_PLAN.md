# Commit plan — single commit to `main`

You don't need the feature branches. For a solo repo of already-tested work, one commit straight to
`main` is simpler and avoids the shared-file juggling entirely. Here's the whole thing in one place.

> Copy the bundle files into your repository working tree first (the ones in
> `joinville_dashboard_update_LATEST_*/`), then run the steps below **inside your repo**.

---

## Step 1 — clean the rain masters once (do this BEFORE committing)

So the station masters, the audit report, and the regenerated page outputs are all consistent in the
same commit:

```bash
python scripts/rain_qc.py        # flags inch-code/ceiling/gap-dump in data/hourly + data/daily (in place)
```

This also writes `data/processed/rain_qc_flags.csv`. (It's idempotent — safe to run again.)

## Step 2 — stage everything and commit to main

```bash
git checkout main
git add -A
git commit -m "Dashboard overhaul: QC (river stage / rain inch-code / wind vane), ENSO overlay, WRF forecast (basins+bairros, regional figure, grid archive, test risk-alert), Ciência Cidadã page, scientific-validity audit"
git push origin main
```

`git add -A` stages every new and changed file. If you'd rather be explicit, this is the full set:

```bash
# scripts (new + modified)
git add scripts/rain_qc.py scripts/archive_wrf_grid.py scripts/build_states_overlay.py \
        scripts/fetch_wrf.py scripts/build_enso.py scripts/build_wrf_basins.py \
        scripts/build_hourly_daily.py scripts/update_datasets.py scripts/build_site_data.py \
        scripts/build_river.py scripts/build_disasters.py scripts/build_station_history.py \
        scripts/build_gauges_city.py scripts/build_city_history.py scripts/make_standalone_rio.py

# notebooks
git add notebooks/Joinville_dashboard_pipeline.ipynb notebooks/joinville_meteo_consolidation.ipynb \
        notebooks/CPTEC_WRF_Joinville_downloader.ipynb

# pages (all nine — the "Ciência cidadã" nav link is on every page)
git add site/index.html site/cidade.html site/cidade_tempchuva.html site/estacao.html \
        site/rio.html site/risco.html site/previsao.html site/sobre.html site/ciencia_cidada.html

# cleaned station masters (only prec cells changed) + processed
git add data/hourly/*.csv data/hourly/*.parquet data/daily/*.csv data/daily/*.parquet
git add data/processed/rain_qc_flags.csv data/processed/gauge_city_daily.csv data/gauges/gauge_city_daily.csv

# regenerated site data outputs
git add site/data/snapshot.json site/data/city_history.json site/data/station_history.json \
        site/data/river.json site/data/river/ site/data/stations/ \
        site/data/disasters.json site/data/enso.json \
        site/data/wrf_forecast.json site/data/wrf_basins.csv site/data/wrf_basins.geojson \
        site/data/wrf_basins_hourly.csv site/data/wrf_bairros.csv site/data/wrf_bairros.geojson \
        site/data/wrf_grid.geojson site/data/wrf_grid_archive.csv site/data/wrf_regional.png \
        site/data/geo/estados_sul.geojson site/data/ciencia_cidada.csv

# workflows + docs
git add .github/workflows/forecast-wrf.yml .github/workflows/update-data.yml \
        .github/workflows/citizen-science-sync.yml
git add METODOLOGIA_DADOS.md CIENCIA_CIDADA_SETUP.md logs/Joinville_dashboard_forecast_log.md

git commit -m "Dashboard overhaul: QC + ENSO + WRF forecast + Ciência Cidadã + validity audit"
git push origin main
```

> **README note:** the bundle's `README.md` is a guide to *this update*. If your repo already has a
> README you want to keep, rename the bundle one (e.g. `UPDATE_NOTES.md`) before committing, or merge
> the parts you want.

## Step 3 — after the push (one-time)

1. **GitHub Pages** → serve the site **directly from the branch** (Settings → Pages → Source: *Deploy
   from a branch* → `main`, folder `/site`). This is what makes the daily WRF commits go live.
2. **Ciência Cidadã** → follow `CIENCIA_CIDADA_SETUP.md` (create the Google Form, paste its embed link
   into `site/ciencia_cidada.html`, publish the responses Sheet as CSV, set the repo variable
   `CITIZEN_SHEET_CSV_URL`).
3. **Smoke-test the WRF Action** → Actions tab → *WRF forecast (daily)* → *Run workflow* (its GRIB path
   only runs in CI, so this is the first real check). `cfgrib`/`eccodes` are installed by the workflow.

---

## What's in this commit (features)

| Feature | Key files |
|---|---|
| River-stage QC (cota vs datum, estuary, tides, MAD window) | `build_river.py`, `site/rio.html`, `river*.json` |
| **Rain QC** — inch-code (254 mm=10 in ×1092) + ceiling + catch-up dumps, flagged with audit trail | `rain_qc.py`, `build_hourly_daily.py`, `update_datasets.py`, cleaned masters, `rain_qc_flags.csv` |
| **Wind QC** — calm + stuck/absent-vane exclusion on the rose | `build_site_data.py`, `snapshot.json`, `index.html` |
| ENSO overlay (NOAA ONI, 5-season rule, auto-fetch) | `build_enso.py`, `enso.json`, `update-data.yml` |
| WRF forecast (basins+bairros, regional figure w/ SC+Joinville, local time) | `build_wrf_basins.py`, `fetch_wrf.py`, `build_states_overlay.py`, `previsao.html`, `wrf_*`, `forecast-wrf.yml` |
| **WRF grid archive** (cumulative native-resolution history) | `archive_wrf_grid.py`, `wrf_grid_archive.csv` |
| **Forecast risk-alert** (OMM logic on the forecast, "fase de teste") | `site/previsao.html` |
| **Ciência Cidadã** page + Form→CSV sync | `ciencia_cidada.html`, `citizen-science-sync.yml`, `CIENCIA_CIDADA_SETUP.md`, `ciencia_cidada.csv` |
| Whole-dashboard scientific-validity audit + methodology/docs | `sobre.html`, `METODOLOGIA_DADOS.md`, `notebooks/Joinville_dashboard_pipeline.ipynb`, all pages' nav |

## Notes
- `fetch_wrf.py` mirrors the verified notebook; its GRIB path only runs in CI — smoke-test via
  `workflow_dispatch` after committing. The intermediate `.nc` is written to `/tmp` in CI and **not**
  committed — only the derived `site/data/wrf_*` files are.
- `git status` in your repo will confirm exactly which files are new vs modified against your baseline.
- Public repo ⇒ unlimited Actions minutes; the daily WRF commit uses `[skip ci]` and keeps the repo
  active (avoids GitHub's 60-day auto-disable of scheduled workflows).
