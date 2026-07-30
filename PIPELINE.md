# Automated data pipeline

How the Joinville datasets stay up to date, for free, with almost no manual work.

```
  data/incoming/  (you drop new .dat / gauge CSV here, weekly)
        │  git push
        ▼
  GitHub Action  "Update datasets"  (.github/workflows/update-data.yml)
        │   1. update_datasets.py  → append into datasets/{5min,hourly,daily}/ masters (dedup)
        │   2. fetch_airport.py    → refresh SBJV from the IEM archive
        │   3. plot_coverage.py    → refresh datasets/figs/coverage_*.png
        │   4. commit the updated masters, clear data/incoming/
        ▼
  datasets/  (Parquet masters, versioned)  →  (later) the dashboard reads these
```

The heavy one-time **historical baseline** is built separately (the notebook, or
`build_station.py` + `build_hourly_daily.py`). This pipeline only *grows* it — each
weekly drop is tiny.

## One-time setup

1. **Create a repo** (public is fine and free) and install **Git LFS** locally
   (`git lfs install`). The Parquet masters are tracked with LFS (see `.gitattributes`).
2. **Add the baseline.** Copy your `datasets/` folder (the Parquet masters + registries)
   into the repo and commit:
   ```bash
   git lfs install
   git add .gitattributes
   git add datasets scripts notebooks *.md requirements.txt .github
   git commit -m "baseline datasets + pipeline"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
   (CSVs are git-ignored on purpose — the repo tracks the compact Parquet; CSVs are
   regenerated locally by the scripts. See the size note below.)
3. **Enable Actions:** they're on by default for the repo owner. That's it — no secrets,
   no server, no cost.

## Weekly routine

Drop the new export files into **`data/incoming/`** and push (drag-and-drop in the
GitHub web UI works too):

- Campbell `*_5.dat` / `*_HR.dat` / `*_DIARIA.dat` — routed automatically by table type
  and station (read from the TOA5 header).
- Rain-gauge CSV (wide `date` + one column per gauge) — name it with `pluvi`/`gauge`/`chuva`.

The push triggers the **Update datasets** Action, which appends everything into the
masters, de-duplicates, refreshes the airport series and coverage figures, commits the
result, and empties `data/incoming/`. There's also a Monday safety-net run and a manual
**Run workflow** button. The airport updates itself — you never add it by hand.

## Run the same update locally (optional)

```bash
pip install -r requirements.txt
python scripts/update_datasets.py --incoming data/incoming --datasets datasets
python scripts/fetch_airport.py          # needs internet
```

## Scripts

| script | role |
|---|---|
| `toa5.py` | readers for `.dat` and the year-sheet spreadsheets |
| `build_station.py` | build a 5-min master (baseline / re-build) |
| `build_hourly_daily.py` | build hourly + daily masters (baseline / re-build) |
| `update_datasets.py` | **incremental weekly append** (what the Action runs) |
| `fetch_airport.py` | refresh SBJV from the IEM ASOS archive |
| `plot_coverage.py` | coverage heatmaps for `datasets/figs/` |

## Repo size / Git LFS note

The Parquet masters are compact, but the **5-minute** archive is the largest piece and
grows over time. GitHub's free Git-LFS quota is **1 GB storage / 1 GB bandwidth per
month** — comfortable for a good while. If you ever want to keep the repo lean, uncomment
`datasets/5min/` in `.gitignore` to keep the high-resolution archive **out** of the repo
(maintained locally), while the pipeline still tracks the hourly + daily masters that the
dashboard actually needs.

## Dashboard, forecast & archive workflows (live)

The dashboard is **live** on GitHub Pages, fed by several workflows beyond the ingestion one above:

- **`update-data.yml`** — on each data push (and weekly), rebuilds the per-page products from the
  masters: `build_site_data.py` (page **Agora** snapshot + the multi-hazard **risk alert**, below),
  `build_city_history.py`, `build_station_history.py`, `build_gauges_city.py`, `build_river.py`,
  `build_enso.py` (live NOAA ONI).
- **`forecast-wrf.yml`** — **daily**: `fetch_wrf.py` downloads the latest CPTEC/INPE WRF (AMS 7 km)
  run — rain, 2 m temperature, 10 m wind, and **2 m relative humidity** (`rh2_pct`) when the product
  exposes it — and `build_wrf_basins.py` area-weights it onto basins/bairros (`wrf_forecast.json` +
  CSV/GeoJSON + regional figure/maps), then `archive_wrf_grid.py` appends the run to the
  **year-chunked grid archive** (`site/data/wrf_archive/grade_AAAA.csv` + `.csv.gz` + `index.json`).
- **`pages.yml`** — deploys `site/**` to GitHub Pages.
- **`snapshot-release.yml`** (manual) — bundles the archive + station masters into a GitHub Release;
  with the Zenodo–GitHub integration on, each release mints a citable **DOI** (see `DATA_ARCHIVE.md`).

### Risk alerts (observed and forecast)
Two alert panels share the **same thresholds**: **Agora** (observed, worst online station, in
`build_site_data.py`) and **Previsão** (forecast, worst bairro, in `previsao.html`). Hazards:
**rain** (OMM intensity classes), **wind** (Beaufort — WMO-No. 306; Atenção ≥ 10.8, Alerta ≥ 17.2 m/s
sustained), **temperature** (provisional bands: heat ≥ 32/≥ 36 °C, cold-frost ≤ 5/≤ 3 °C) and a
**heat index / "sensação"** (apparent temperature from temp × RH; Steadman 1979 / NWS Rothfusz 1990;
Atenção ≥ 32, Alerta ≥ 41 °C apparent). All are **"fase de teste" — guidance, not an official Defesa
Civil warning**. Full methodology + citations: `METODOLOGIA_DADOS.md` and `site/sobre.html`.
