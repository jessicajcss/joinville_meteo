# Joinville Dashboard — build log (Stage-A, operational-dashboard branch)

Companion to the main lab log. Every decision scientifically grounded, no hallucination.
Tags: **[Established]**, **[Design choice]**, **[Verified]**. (Full living copy also in the
claude.ai Project **UDESC** → `claude/Joinville_dashboard_forecast_log.md`.)

*Jess (with Claude/Cowork), 2026-07-26.*

---

## Decisions

| # | Decision | Tag |
|---|----------|-----|
| D14 | WRF forecast carries rain + temp + wind, by basin and bairro | [Design choice] |
| D15 | One `.nc` serves dashboard + Stage-A verification (processor crops to Joinville) | [Design choice] |
| D16 | Area-weighting in EPSG:31982; uniform-field invariant as the correctness test | [Established] |
| D17 | Bairro choropleth uses a minimum colour span per variable (no false drama) | [Design choice] |
| D18 | Once-daily WRF auto-update via scheduled Action (`fetch_wrf.py`) | [Design choice] |
| D19 | Previsão times shown LOCAL (UTC−3); run cycle keeps UTC label (00Z/12Z) | [Established] |
| D20 | Faint real SC + Joinville outlines on the regional figure (IBGE-derived) | [Established] |
| D21 | `wrf_grid.geojson` coords rounded to 3 decimals (2.39 → 1.83 MB) | [Design choice] |
| D22 | Regional figure uses true geographic aspect (no flattening) | [Established] |
| D23 | Wind-rose QC: exclude calm (<0.5 m/s, report calm %) + drop stuck-vane stations (>25 % at exactly 0°) | [Established] |
| D24 | Whole-dashboard text/caption/table audit — every page matched to the data | [Established] |

## Key verified results

- **Rain QC** (`scripts/rain_qc.py`). Inch-based tipping buckets (tip 0.254 mm = 0.01 in); logger
  fault code = exact inch value: **254.0 mm = 10 in, ×1,092** (99.9th & 99.99th percentiles both
  exactly 254.0 — sentinel signature), **228.6 mm = 9 in, ×6**. Plus gross spikes (1606.8, 961.8 mm/h)
  and catch-up dumps (big value after a multi-hour gap). Rule flags (never deletes): `inch_code`,
  `ceiling` >150 mm/h or 350 mm/day, `gap_dump` (≥40 mm after >2 h gap) → **NaN, not 0**. Runs at the
  end of `build_hourly_daily.py` + `update_datasets.py`. Audit trail `data/processed/rain_qc_flags.csv`.
  **1,236 points flagged (~0.14 %); ~20,500 mm spurious rain removed across 41 station-months**
  (udesc May 2025 1,721 → 114 mm); max kept 48–115 mm/h; city annual 2,052–2,056 vs ~2,130 mm ref. **[Verified]**
- **Wind-rose QC** (`build_site_data.wind_rose`). aguasdejoi/rodovia report wd exactly 0° for ~41 % of
  *windy* hours (ceasa 76.5 % recent) = stuck/absent vane. Excluding calm + broken vanes turns a false
  N/S peak into the physically expected **East quadrant (sea breeze)**; page reports calm % (~44 %),
  valid-vane count, and exclusions. **[Verified]**
- **WRF field processing** cross-checked vs the validated methodology: rain de-accumulated
  (`tp ≈ acpcp + ncpcp`, residual 0.089 mm), temp/wind instantaneous (never differenced). Area-weighting
  uniform-field invariant holds for rain/temp/wind on basins and bairros. **[Verified]**

## Page audit fixes (D24)

Cidade·Temp×Chuva: rain source corrected to gauge + meteo-station blend (4 captions). Agora legend
"online (hoje)" → "online (leitura recente)" (8-day freshness). Chuva–Rio: level QC text now states
median ± max(6·MADn, physical span −2.8/+3.5 m). Risco: "Situação" filter includes "Não informado".
Estação: audited, already consistent.

## Storage / quota (answers on record)

- WRF outputs are **overwritten** each run — live site holds one copy; git history grows only by small
  deltas (grid geometry identical run-to-run). WRF CSVs are **snapshots** (not cumulative across runs).
- Repo is **public → unlimited GitHub Actions minutes** (four workflows ~270–300 Linux-min/month).
  Daily WRF commit uses `[skip ci]`, keeps repo active (avoids 60-day scheduled-workflow auto-disable).
- All displayed/output data is **local time (UTC−3)**; only the WRF run cycle and the build timestamp
  are labelled UTC.

## References used

USGS (stage/cota); Rousseeuw & Croux 1993 (MAD, 1.4826); De Mello 2020 & Rodrigues 2015 (Joinville
rain / Serra do Mar orography); NOAA/CPC ONI (ENSO); WRF Users' Guide + ECMWF (accumulation);
SIRGAS 2000/UTM 22S (EPSG:31982); WMO-No. 8 (physical-plausibility QC with flagging); IBGE malhas
(state outlines); SEPROT/Prefeitura de Joinville (primary data).
