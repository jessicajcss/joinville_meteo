# Joinville · Monitoramento Meteorológico

An interactive, free, auto-updating weather dashboard for **Joinville (SC)**, built from
your automatic weather stations and neighborhood rain gauges. It is a **static site**:
a GitHub Action cleans the data and renders the dashboard to plain HTML, which
GitHub Pages serves for free with no server and no usage limits.

> **Why static instead of a live Shiny server?** Your data updates about once a week,
> so nothing needs a running server between updates. A static site is free forever,
> always online, fast, and rebuilds itself automatically each time you upload new data.

## Features — risk alerts, forecast & data archive

- **Risk alerts** on **Agora** (observed) and **Previsão** (forecast), with the same thresholds:
  rain (OMM), wind (Beaufort, WMO-No. 306), temperature (provisional bands), and a **heat index /
  "sensação"** from temperature × humidity (Steadman 1979 / NWS Rothfusz 1990). Marked **"fase de
  teste" — guidance, not an official warning**.
- **WRF forecast** (CPTEC/INPE AMS 7 km) by basin and bairro, updated daily, now including **2 m
  relative humidity** (feeds the heat-index alert).
- **Year-chunked WRF grid archive** (`site/data/wrf_archive/`), preserved with a citable **Zenodo DOI**.

Full methodology and **citations** are in `METODOLOGIA_DADOS.md`, `DATA_ARCHIVE.md`, and the public
**Sobre** page (`site/sobre.html`).

---

## How it works

```
  data/raw/ (you drop new files weekly)
        │
        ▼
  scripts/build_data.py   ──►  data/processed/  (small, clean, dashboard-ready)
        │                        · daily.csv, recent.csv
        │                        · latest.json, summary.json
        │                        · events.csv  (extreme-rain flags)
        │                        · pluvio_daily.csv, pluvio_latest.json
        │                        · *.geojson   (Joinville limits, bairros, bacias)
        ▼
  index.qmd (Quarto dashboard) ──► _site/index.html ──► GitHub Pages (public URL)
```

The heavy raw files (tens of MB) are **never** loaded by the browser — the pipeline
pre-aggregates them into ~1.5 MB of processed data, so the page stays fast.

---

## Quick start — from zero

You need a free [GitHub](https://github.com) account. No credit card, no paid plan.

1. **Create a repository.** On GitHub click **New repository**, name it e.g.
   `joinville-meteo`, set it to **Public**, and create it.
2. **Upload these files.** Easiest way: on the repo page click
   **Add file → Upload files**, then drag in everything from this folder
   (keep the folder structure). Commit.
   *Or*, with git installed:
   ```bash
   git init && git add . && git commit -m "initial dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-user>/joinville-meteo.git
   git push -u origin main
   ```
3. **Turn on GitHub Pages.** Repo **Settings → Pages → Build and deployment →
   Source: GitHub Actions**. (You only do this once.)
4. **Watch it build.** Open the **Actions** tab — the "Build & deploy dashboard"
   workflow runs (~2–4 min). When it finishes, your dashboard is live at:
   ```
   https://<your-user>.github.io/joinville-meteo/
   ```

That URL is public — share it freely.

---

## Weekly update routine

Whenever you have new data, just replace the files in **`data/raw/`**:

- **In the browser:** open `data/raw/`, click **Add file → Upload files**, drop the
  new CSVs (same names, e.g. `iateclube_raw.csv`), and commit.
- **With git:** copy the new files into `data/raw/`, then
  `git add data/raw && git commit -m "data <date>" && git push`.

That's it. The push triggers the Action, which re-cleans the data, re-renders the
dashboard, and republishes — the live site updates in a few minutes. There is also a
weekly scheduled rebuild (Mondays) as a safety net, and a manual **Run workflow**
button in the Actions tab.

### What the pipeline expects in `data/raw/`

| File | What it is |
|------|-----------|
| `<code>_raw.csv` | one per station — columns `date` (ISO-8601 UTC) plus any of `temp, umid, ws, wd, prec` |
| `pluviometros_raw.csv` | rain gauges, wide format: `date` + one column per neighborhood |
| `stations.xlsx` | station metadata: `Longitude, Latitude, Elevation, code, Station` |
| `stations_pluv_ID.xlsx` | gauge metadata (same columns + `station_code`) |
| `data/geo/*.shp` | the Joinville GIS layers (limit, bairros, bacias) — set once, rarely change |

Stations missing a column (e.g. the airport has no `prec`) are handled automatically;
a station file that isn't there yet is simply skipped.

---

## Run it locally (optional)

```bash
pip install -r requirements.txt
# install Quarto once: https://quarto.org/docs/get-started/
python scripts/build_data.py         # builds data/processed/
quarto preview index.qmd             # opens the dashboard with live reload
```

---

## Customizing

- **Alert thresholds.** Edit `RAIN_ALERTS` near the top of `scripts/build_data.py`
  (daily-rainfall mm cutoffs for *Atenção / Alerta / Crítico*). Tune these to the
  Defesa Civil de Joinville criteria.
- **Add / remove stations.** Add a row to `stations.xlsx` and drop the matching
  `<code>_raw.csv` in `data/raw/`. Nothing else to change.
- **Colors & layout.** Palette lives in `custom.scss` and at the top of `index.qmd`
  (a colorblind-safe categorical + status palette). Layout is the `# Page` /
  `## Row` / `### Column` structure in `index.qmd`.
- **Language.** All labels are in Portuguese in `index.qmd`; change them there.

---

## A note on data size (read before you have a year of history)

Your raw station files are large (tens of MB each). Committing a fresh copy every
week makes the git history grow over time. Two easy options when that becomes a
concern:

1. **Git LFS** — track big files efficiently:
   ```bash
   git lfs install
   git lfs track "data/raw/*.csv"
   git add .gitattributes
   ```
   (GitHub's free LFS quota is 1 GB storage / 1 GB bandwidth per month.)
2. **Keep raw out of git** — upload raw data as a *Release asset* or pull it from
   Google Drive inside the Action, and commit only `data/processed/`. Ask and this
   repo can be switched to that pattern.

For the first months, plain commits are perfectly fine — start simple.

---

## Files

```
├── index.qmd                 # the dashboard (Quarto + Python)
├── custom.scss               # theme / colors
├── _quarto.yml               # project config
├── requirements.txt          # Python deps
├── scripts/build_data.py     # the data pipeline
├── data/
│   ├── raw/                  # you drop weekly data here
│   ├── geo/                  # Joinville shapefiles (set once)
│   └── processed/            # generated by the pipeline (git-ignored)
└── .github/workflows/build.yml   # the automation
```

---

Built for the UDESC extreme-events response project · dashboard in Portuguese,
data in local time (America/São_Paulo).
