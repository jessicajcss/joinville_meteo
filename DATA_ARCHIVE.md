# Data archive — layout, formats and long-term preservation

This dashboard publishes two growing, quality-controlled datasets. This note documents how they
are stored, how to download slices of them, and how to guarantee they stay available for years.

## 1. What accumulates

**Station master series** — consolidated from the SEPROT / Defesa Civil de Joinville loggers into
three resolutions per station, all served under `site/data/stations/`:

| Resolution | Path | Format |
|---|---|---|
| 5-minute (raw) | `stations/fivemin/<code>/<code>_<year>.csv.gz` | year-chunked, gzipped |
| hourly | `stations/hourly/<code>.csv.gz` | gzipped |
| daily | `stations/daily/<code>.csv` | plain CSV |

The Estação → "Baixar dados" panel already lets a user pick station, resolution and a **date range**
(client-side), so these are downloadable in slices today.

**WRF forecast grid archive** — every CPTEC/INPE WRF (AMS 7 km) run's per-cell hourly forecast over
the Joinville window, appended so the model history persists after the per-run files are overwritten.
As of this change it is **chunked by calendar year** under `site/data/wrf_archive/`:

```
site/data/wrf_archive/
  grade_2026.csv        one plain-CSV file per year (universally openable)
  grade_2026.csv.gz     the same, gzip-compressed (~5–10× smaller; opens directly in pandas/R)
  grade_2027.csv ...
  index.json            manifest (years, date ranges, row counts, byte sizes)
```

Row schema (long format), one row per run × valid-hour × grid cell:

```
run_time_utc, valid_time_local, lead_h, i, j, lat, lon,
rain_mm_h, temp_degC, u10_ms, v10_ms, wind_ms, wind_dir_deg
```

`valid_time_local` is Joinville local time (UTC-3); `run_time_utc` is the model cycle in UTC (00Z/12Z).

### `index.json` manifest

```json
{
  "columns": [...],
  "legacy_migrated": true,
  "years": [
    {"year": "2026", "csv": "grade_2026.csv", "gz": "grade_2026.csv.gz",
     "rows": 900, "first": "2026-07-26 04:00", "last": "2026-07-26 12:00",
     "bytes_csv": 79075, "bytes_gz": 10417}
  ],
  "total_rows": 900,
  "generated_at": "..."
}
```

The Previsão download panel reads this manifest and offers a **year (or "all years") + format (CSV /
CSV.gz)** picker; single years link straight to the stored file, "all" is concatenated in the browser.
If the manifest is ever missing, the panel falls back to the legacy single file so the data is always
reachable.

## 2. Why year-chunking (the maintenance win)

- **No 100 MB wall.** A single ever-growing CSV would hit GitHub's per-file limit (~25 MB/year → ~4 yr).
  Per-year files stay small; each closed year is immutable.
- **No git-history bloat.** `archive_wrf_grid.py` only ever rewrites the *current* year's file, written
  deterministically (sorted rows, gzip `mtime=0`), so unchanged years produce byte-identical output and
  git records no diff. The previous design rewrote the whole file every run.
- **Non-destructive migration.** The old `site/data/wrf_grid_archive.csv` is folded into the yearly files
  once, row for row (verified: 0 rows lost), then left in place as a frozen backup.

## 3. Long-term preservation → Zenodo DOI (recommended)

GitHub Pages serves the current files well, but it is not a preservation guarantee. To keep the dataset
available and **citable** for years, archive versioned snapshots to a research-data repository. The
standard, free option is **Zenodo**, which integrates with GitHub Releases and mints a DOI per release.

**One-time setup (only you can do these — they need your account):**

1. Sign in at <https://zenodo.org> with your GitHub account.
2. Go to Zenodo → *GitHub* settings (<https://zenodo.org/account/settings/github/>) and flip the toggle
   **ON** for this repository. (Zenodo installs a webhook; nothing to paste into the repo.)
3. The repository already contains **`.zenodo.json`**. Before publishing, edit it so:
   - **`creators[].name`** is your real name in `Sobrenome, Nome` order (replace the `EDITE AQUI…` placeholder).
   - **`license`** is a **lowercase SPDX id** — `cc-by-4.0`, **not** `CC-BY-4.0` (uppercase is rejected). Confirm
     the license is compatible with the source-data terms (observations from SEPROT / Defesa Civil; WRF from
     CPTEC/INPE) before choosing it.
   - Add **`"orcid": "0000-0000-0000-0000"`** to your creator entry **only if** you have a valid ORCID. An
     empty `"orcid": ""` is invalid and makes Zenodo reject the release — so omit the field if you have none.
4. Cut a release. Either use the GitHub UI (Releases → *Draft a new release* → tag e.g. `data-2026-07-28`),
   or run the **"Data snapshot release"** workflow (Actions → *Data snapshot release* → *Run workflow*),
   which bundles the archive + station masters into a zip and publishes a dated release.

Each published release is then archived by Zenodo with its own DOI, plus a concept-DOI that always points
at the latest version. Cite the concept-DOI in papers.

**If a release shows "Failed" in Zenodo:** the GitHub release itself is fine — Zenodo's archiving step
rejected the metadata. Open the **Zenodo panel on GitHub → Errors tab** to see the exact message
(`Extra metadata load failed` = a bad `.zenodo.json`, usually the license case or an empty `orcid`). Fix
`.zenodo.json`, commit and push, then **create a *new* release** (or delete and re-create the failed one) —
editing metadata alone does not re-trigger Zenodo; only a newly published release does. Note Zenodo archives
the repository's source snapshot at the tag (which already includes `site/data/…`), not the release's zip
asset, so the data is captured either way.

> Alternatives to Zenodo: your university/institutional repository, or PANGAEA (geoscience-focused). The
> principle is the same — immutable, versioned, externally-hosted snapshots.

## 4. Data sources & how to cite

**Station observations** — SEPROT / Defesa Civil de Joinville station and rain-gauge network.

**WRF forecast** — CPTEC/INPE, model output from `dataserver_modelos/wrf/` on the INPE/CGIP/COIDS
server, provided under Brazil's federal open scientific-data policy. Suggested citation (INPE):

> "Dados de previsão/simulação numérica do modelo WRF fornecidos pelo Instituto Nacional de Pesquisas
> Espaciais (INPE), através do Sistema de Transferência de Dados da Coordenação-Geral de Infraestrutura
> e Dados / Divisão de Operações (CGIP/COIDS/CPTEC), acessado em [Data de Acesso] via
> https://dataserver.cptec.inpe.br/."

When you publish a Zenodo snapshot, cite both the source datasets above and this dataset's own DOI.

## 5. Format notes (size)

Renaming CSV to `.txt` does **not** save space (both are plain text). Real size levers:

- **gzip** (`.csv.gz`) — ~5–10× smaller; pandas/R open it transparently, Excel needs an unzip step. The
  archive and the hourly/5-min station files use this.
- **Parquet** — smaller and typed, but not human-openable; good as an *internal* master, poor as a public
  download. Plain CSV remains the most future-proof public format.
- **Trim redundancy** — the archive keeps `u10`, `v10`, `wind_ms` and `wind_dir_deg`; speed and direction
  are derivable from `u10`/`v10`, so two columns could be dropped if size ever demands it.
