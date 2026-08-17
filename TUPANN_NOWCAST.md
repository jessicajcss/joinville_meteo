# TUPANN Nowcast — independent dashboard layer

A **satellite-nowcast** layer for the Joinville Meteo dashboard, added **without touching any existing
file**. It shows TUPANN's short-lead rain forecast (next +30 to +120 min) at **three scales — 2 km grid,
hydrographic basin, and municipal district (bairro)** — with a **calibrated warning** per area. It is the
deployment (notebook 10) of the research pipeline (v2.1 → 05e → 07b → 08 → 09).

> **Fase de teste.** Research product of LaCiA/UDESC. **Not an official Defesa Civil warning.**

## What was added (all NEW files — nothing existing was modified)

| new path | role |
|---|---|
| `site/nowcast.html` | the independent **page** (own rail entry, native look, Leaflet, 3-scale toggle) |
| `site/data/tupann/` | the independent **subfolder** — all `tupann_*` products live here |
| `site/data/tupann/incoming/` | drop-zone for the upstream model field (`field_latest.npz`) |
| `scripts/build_tupann_nowcast.py` | CPU builder: field → grid/basin/bairro products + warnings |
| `scripts/push_tupann_field.py` | upstream (GPU/ONNX) publish step → writes `incoming/field_latest.npz` |
| `.github/workflows/forecast-tupann.yml` | independent Action: build products from the latest field + commit |
| `TUPANN_NOWCAST.md` | this file |

**The one optional edit (yours to make, not done automatically).** To show *Nowcast* in the menu of the
*other* pages, add one entry to each page's `NAV` array:
`['nowcast','Nowcast','nowcast.html']` (place it after the `previsao` entry). The nowcast page already
links to every other page, so it is fully reachable without this; the edit only adds the reverse link.

## The loop

```
  TUPANN + U-Net (07b/08) + calibration        [GPU or ONNX-CPU, upstream]
        │   push_tupann_field.publish(field2d, lat2d, lon2d, issue_utc, lead_min, tau_*)
        ▼
  site/data/tupann/incoming/field_latest.npz   ── git push ──▶ triggers the Action
        │
        ▼   .github/workflows/forecast-tupann.yml   (ubuntu, CPU, geopandas — seconds)
  scripts/build_tupann_nowcast.py  ──▶  site/data/tupann/tupann_{grid,basins,bairros}.geojson
                                        + tupann_*.csv + tupann_warnings.json + tupann_meta.json
        │
        ▼   pages.yml (existing, 6-hourly schedule) publishes site/
  site/nowcast.html  ── reads the products, draws the map + warnings
```

## Two deployment shapes (pick per your compute)

- **Option B — external-GPU push (recommended first).** Run TUPANN + the calibrated U-Net where a GPU is
  (your Colab, or a small VM), call `push_tupann_field.publish(...)`, git-push the `incoming/` field. The
  Action does the rest on CPU. Keeps the dashboard side pure-CPU and free.
- **Option A — ONNX-CPU in the Action.** Export the TUPANN checkpoint to ONNX and run inference on the
  runner directly from fresh `s3://noaa-goes19` RRQPE. Fully autonomous, heavier to set up. The forward
  pass is CPU-fast (~1 s / patch); the blocker is only the input feeds (RRQPE@issue, live wind).

Both keep the free/global/replicable stack (RRQPE + ERA5/station wind + GLO-30 DEM). See
`Joinville_operational_requirements.md` §6 and `Joinville_GHA_deployment.md`.

## Data contract (what the page reads)

- `tupann_meta.json` — model, `issue_utc`, `lead_min`, `tau_mod`, `tau_heavy`, grid/zone counts, `generated_at`, `phase`.
- `tupann_warnings.json` — ranked list of basins/bairros at LARANJA/VERMELHO (worst first) + `n_red`/`n_orange`.
- `tupann_basins.geojson` / `tupann_bairros.geojson` (+ `.csv`) — geometry + `mean/max/p90_mm_h`, `area_ge_mod_pct`, `area_ge_heavy_pct`, `level`.
- `tupann_grid.geojson` — 2 km cell points (within the municipality) with `rain_mm_h` + `level` (thinned to ≤4000 for the web).

The builder reads the existing `site/data/{bacias,bairros,limite}.geojson` **read-only** and writes only `tupann_*`.

## Warnings = the calibrated operating point (not raw intensity classes)

Levels come from a **decision threshold τ per tier** applied to the nowcast rain-rate:
`VERMELHO ≥ τ_heavy` (predicts a ≥8 mm/h event), `LARANJA ≥ τ_mod` (≥4 mm/h), `AMARELO ≥ τ_mod/2`, else `VERDE`.
TUPANN **under-warns** at the heavy tail, so raw intensity thresholds miss events; the **calibration (nb 05e /
07b §14)** lowers τ to recover recall. **τ is model-specific — refit it whenever the model changes.** The τ
values travel in the incoming `.npz` meta, so the calibrated numbers flow straight through. Zone level is
driven by the area's **p90** (worst decile) so an intense core is not diluted by the area mean.

## Run / test locally

```bash
# 1) make a field (or use push_tupann_field.publish from your inference code)
python scripts/push_tupann_field.py                      # writes a demo incoming/field_latest.npz
# 2) build the products
python scripts/build_tupann_nowcast.py \
    --field site/data/tupann/incoming/field_latest.npz --data site/data --out site/data/tupann
# 3) open site/nowcast.html (any static server)
```

## References
Catão et al. (2025) TUPANN; Ronneberger (2015) U-Net; Ayzel (2020) RainNet (GMD); Harris (2022, JAMES) &
Leinonen (2021, IEEE TGRS) downscaling; Roberts & Lean (2008) FSS; Ferro & Stephenson (2011) SEDI.
Operating-point calibration: nb 05e / 07b §14. Aggregation mirrors `scripts/build_wrf_basins.py`.
