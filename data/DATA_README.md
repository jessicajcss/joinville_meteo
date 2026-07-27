# Joinville — Meteorological & Hydrological Data: Documentation and Inventory

This document describes the consolidated dataset built from the automatic weather /
hydrological stations of the **Defesa Civil de Joinville** network, the municipal
**rain-gauge** network, and the **SBJV airport** (Joinville) surface observations.

**Guiding principle (data integrity).** Every value in these datasets is a *native
product of the datalogger* (or of the airport's official METAR archive). Nothing is
interpolated, gap-filled, or synthesised. Real gaps (sensor outages, station downtime)
are left as gaps. The only *derived* quantities are clearly labelled daily means
(Section 5) computed by a documented, standard method.

- **Period:** 2011 – 2026 (varies by station; see inventory).
- **Time zone:** local standard time, `America/Sao_Paulo` (the loggers record local time).
- **Units:** SI-friendly — temperature °C, wind **m/s** (converted from the loggers'
  km/h), rainfall mm, pressure hPa, radiation W/m², river level m.
- **Three temporal resolutions per station:** `5min`, `hourly`, `daily`.

---

## 1. Stations

| code | name | type | lat | lon | elev (m) | resolution | notes |
|---|---|---|--:|--:|--:|:--:|---|
| ceasa | Ceasa | meteorological | −26.2538 | −48.9111 | 24 | 5 min | temp/RH sensor fails from ~2024 |
| iateclube | Joinville Iate Club | hydrometeorological | −26.2925 | −48.7802 | 2 | 5 min | + river level |
| flotflux | Cachoeira – Área Central | hydrometeorological | −26.2753 | −48.8492 | 4 | 5 min | + river level |
| cubatao | Cubatão | hydrometeorological | −26.1949 | −48.9114 | 25 | 5 min | ends 2023-08 |
| itaum | Itaum | meteorological | −26.3451 | −48.8161 | 60 | 5 min | ends 2024-12 |
| aguasdejoi | Cia. Águas de Joinville (Bucarein) | hydrometeorological | −26.3218 | −48.8381 | 4 | 5 min | ends 2024-07 |
| rodovia | Rodovia do Arroz (Estrada Sul) | meteorological | −26.3738 | −48.9524 | 11 | 5 min | 5-min gap 2014–2020 |
| guanabara | Guanabara | hydrological | −26.3199 | −48.8222 | — | 5 min | rain + level only |
| jardimparaiso | Paraíso (Jardim Paraíso) | hydrological | −26.2192 | −48.8194 | — | 5 min | rain + level only |
| divobras | Unidade de Obras (DIVOBRAS) | hydrological | −26.3093 | −48.8237 | — | 5 min | rain + level only |
| aeroporto | Aeroporto SBJV | airport (METAR/ASOS) | −26.2148 | −48.7975 | 6 | hourly | external source (IEM), see §7 |
| jativoca | Jativoca | hydrometeorological | −26.3694 | −48.8873 | — | — | **no data file located** — mapped site only |

Coordinates are SIRGAS 2000 (EPSG:4674 ≈ WGS-84), from the network's official
coordinate table; the machine-readable registry is `stations_master.csv`.
Station types: *meteorological* = temp/RH/wind/rain; *hydrometeorological* = the above
+ river level; *hydrological* = rain + river level only.

## 2. Rain gauges (pluviômetros)

Eight neighbourhood tipping-bucket gauges, 10-minute resolution. Registry:
`gauges_master.csv`.

| code | name | lat | lon |
|---|---|--:|--:|
| aventureiro | Aventureiro | −26.2490 | −48.7970 |
| centro | Centro | −26.3010 | −48.8410 |
| costaesilva | Costa e Silva | −26.2790 | −48.8650 |
| estacaocidadania | Estação da Cidadania | −26.3310 | −48.8750 |
| estradageral | Estrada Geral do Salto | −26.2960 | −48.9880 |
| iririu | Iririú | −26.2730 | −48.8280 |
| paranaguamirim | Paranaguamirim | −26.3470 | −48.7810 |
| itinga | Itinga | −26.3830 | −48.8200 |

> **Network change:** the raw gauge file (`pluviometros_raw_2021_2025.csv`, 2021–2025)
> contains **Nova Brasília** but not **Estação da Cidadania**, while the current
> coordinate list is the reverse. The gauge roster evolved over time; both names are
> retained where data exists. *(Open item — confirm which gauges are currently active.)*

## 3. Temporal resolutions & file layout

```
datasets/
├── 5min/<code>.csv     instantaneous / period tables at 5-minute step
├── hourly/<code>.csv   native hourly tables (2011–2026)
├── daily/<code>.csv    native daily extremes/totals + derived daily means
├── stations_master.csv station registry (coords, type, resolution)
├── gauges_master.csv   rain-gauge registry
└── figs/               coverage heatmaps + per-variable inventories
```

Both `.csv` (universal) and `.parquet` (typed, compact) are provided. All timestamps
are local-naive `America/Sao_Paulo`.

## 4. Variable dictionary

Columns present depend on station type (a station only carries what its sensors record).
The **native aggregation** column reports how the *logger* produced each field (from the
TOA5 header metadata): `Avg` arithmetic mean, `Smp` instantaneous sample, `WVc` wind
**vector** average, `Max` period maximum, `Tot` period total.

### 5-min and hourly tables

| column | unit | native agg. | description |
|---|---|:--:|---|
| date | — | — | timestamp (local standard time) |
| temp | °C | Avg | air temperature |
| umid | % | Smp | relative humidity |
| prec | mm | Tot | precipitation in the interval |
| ws | m/s | WVc | wind speed (vector mean; km/h→m/s) |
| wd | ° | WVc | wind direction (vector mean) |
| gust | m/s | Max | wind gust (km/h→m/s) |
| gust_dir | ° | — | gust direction |
| solar | W/m² | Avg | global solar irradiance |
| pressure | hPa | Smp | atmospheric pressure |
| dewpoint | °C | Smp | dew-point temperature |
| heat_index | °C | Smp | heat index (logger-computed) |
| wind_chill | °C | Smp | wind-chill (logger-computed) |
| level | m | Smp | river/water level (hydro stations) |
| level_max, level_min | m | Max/Min | level extremes in the interval |

### daily tables

Native (from the `*_DIARIA` logger table):

| column | unit | native agg. | description |
|---|---|:--:|---|
| temp_max, temp_min | °C | Max/Min | daily temperature extremes |
| umid_max, umid_min | % | Max/Min | daily humidity extremes |
| prec | mm | Tot | daily rainfall total |
| solar_total | (logger total) | Tot | daily total radiation (logger-reported) |
| gust_max | m/s | Max | daily maximum gust |
| gust_dir | ° | — | direction of the daily max gust |
| level_max, level_min | m | Max/Min | daily level extremes |
| dewpoint, heat_index, wind_chill | °C | Smp | daily logger samples |

Derived (computed here — see §5):

| column | unit | method | description |
|---|---|---|---|
| temp_mean, umid_mean, ws_mean, pressure_mean, solar_mean | as above | mean of the day's hourly values | daily means the logger does not store |
| n_hours | count | — | number of hourly values contributing to the means (use to filter partial days) |

## 5. Processing methodology

1. **Parsing.** Campbell **TOA5** files (`.dat`) and the year-sheet spreadsheets
   (`*_HR/_DIARIA (YYYY-YYYY).xlsx`) are read with a single reader that maps logger
   field names to the schema above.
2. **Missing values.** The Campbell sentinels `NAN`, `-100`, `-6999`, `-144.9` (and
   similar) are converted to missing.
3. **Unit conversion.** Wind speed and gust km/h → m/s (÷3.6). Airport source converts
   °F→°C, knots→m/s (×0.514444), inches→mm (×25.4), UTC→local.
4. **Quality control.** Values outside physically plausible ranges are set to missing:
   temp/dewpoint [−10, 50] °C, RH [0, 100] %, precip [0, 500] mm, wind [0, 100] m/s,
   gust [0, 120] m/s, direction [0, 360]°, pressure [800, 1050] hPa, solar [0, 1600] W/m².
   Timestamps before 2010 are discarded (stray logger clock artefacts). These follow the
   spirit of WMO gross-limit checks (WMO-No. 8; see §9).
5. **De-duplication.** When the same timestamp appears in more than one source, the
   record with the **most non-missing fields** is kept.
6. **Daily means (the only derived quantities).** `*_mean` = the **arithmetic mean of
   that calendar day's hourly values**; `n_hours` records how many hours contributed, so
   partial days can be excluded. This is distinct from, and complementary to, the native
   `temp_max`/`temp_min` extremes (a `(Tmax+Tmin)/2` mean can also be formed from those).
7. **Resampling floor.** Hourly timestamps are floored to the hour, daily to the day.

## 6. Data inventory

Row counts, temporal span, and mean monthly completeness (of months that report). The
grey-vs-blue *structure* of the gaps is in `datasets/figs/coverage_{5min,hourly,daily}.png`
and, per variable, in `figs/inventory_<station>_<tier>.png`.

| station | 5-min rows | 5-min span | 5-min | hourly rows | hourly | daily rows | daily |
|---|--:|:--|--:|--:|--:|--:|--:|
| ceasa | 1,017,167 | 2012-04 – 2026-07 | 83% | 71,219 | 80% | 4,791 | 93% |
| iateclube | 1,296,600 | 2012-04 – 2026-07 | 91% | 120,224 | 91% | 5,111 | 93% |
| flotflux | 1,141,699 | 2012-04 – 2026-07 | 92% | 116,622 | 92% | 4,953 | 93% |
| cubatao | 735,357 | 2012-04 – 2023-08 | 70% | 84,477 | 89% | 3,876 | 92% |
| itaum | 752,290 | 2011-12 – 2024-12 | 93% | 54,295 | 88% | 4,327 | 93% |
| aguasdejoi | 721,603 | 2012-04 – 2024-07 | 81% | 71,981 | 79% | 3,230 | 84% |
| rodovia | 278,994 | 2012-04 – 2022-12 | 86% | 49,425 | 88% | 2,172 | 89% |
| guanabara | 290,004 | 2013-08 – 2025-01 | 59% | 99,798 | 84% | 4,629 | 93% |
| jardimparaiso | 494,682 | 2013-08 – 2026-07 | 90% | 113,299 | 96% | 4,739 | 96% |
| divobras | 436,198 | 2021-08 – 2026-07 | 89% | 67,564 | 92% | 2,903 | 93% |

*(aeroporto is built on the first automated run from the IEM archive; jativoca has no
data file.)*

## 7. Sources & provenance

Each station's series is stitched, then de-duplicated, from these source families:

- **`meteo/<code>_raw.csv`** — previously-consolidated clean 5-min series (≈2012–2020).
- **`meteo/meteo_add/*_5.dat`** — full-history 5-min TOA5 dumps.
- **`meteo/defesa_civil/HISTORICO/Joinville/<station>/*_5*.dat`** — the collection
  **fragments** (≈1,800–2,700 small TOA5 files per station). *These are essential*: they
  hold the dense 5-min record for **2021–2026** that no other source contains, and they
  added ~2.6 million 5-min rows across the network.
- **`meteo/defesa_civil/*_5.dat`** — the current rolling 5-min tables (most recent weeks).
- **`meteo/meteo_add/*_HR/_DIARIA (YYYY-YYYY).xlsx`** — native hourly/daily, one sheet per
  year, 2011 → 2024/2026 (primary source for the hourly and daily datasets).
- **`meteo/defesa_civil/*_HR.dat` / `*_DIARIA.dat`** — recent native hourly/daily.
- **Airport (SBJV):** Iowa Environmental Mesonet ASOS archive
  (`mesonet.agron.iastate.edu`), station `SBJV`, `data=all`, refreshed automatically.

## 8. Reproducing / maintaining

- **`notebooks/joinville_meteo_consolidation.ipynb`** — runs the whole build locally
  (VS Code or Colab): set `PROJECT`, `REBUILD=True`; produces all three resolutions,
  coverage heatmaps and per-variable inventories.
- **Scripts** (`scripts/`): `toa5.py` (readers), `build_station.py` (5-min), `build_hourly_daily.py`
  (hourly/daily), `fetch_airport.py` (SBJV), `plot_coverage.py` (inventory figures).

## 9. Known gaps, caveats & data-quality notes

- **rodovia** has no 5-min *or* hourly/daily data for **2014–2020** — a genuine multi-year
  outage present in every table; not recoverable from any source.
- **itaum** gap around 2020; **guanabara / paraíso** are intermittent in their early years.
- **Station end dates:** cubatão ends 2023-08, aguas 2024-07, itaum 2024-12. (Earlier these
  were assumed "decommissioned ~2020"; the HISTORICO fragments show they ran several years
  longer.)
- **Ceasa temperature/humidity** (and derived dew-point/heat-index/wind-chill) read as
  missing from ~2024 — a sensor fault; wind, rain and solar continue. Visible in
  `figs/inventory_ceasa_hourly.png`.
- **aguasdejoi** carried one stray **1990** timestamp in an early build; all pipelines now
  discard timestamps before 2010.
- **pressure** is recorded only at some stations; **river level** only at
  hydro/hydrometeorological stations.
- Completeness percentages are the mean of *reporting* months; consult the coverage figures
  for the position of the gaps.

## 10. References

- World Meteorological Organization, *Guide to Instruments and Methods of Observation*
  (**WMO-No. 8**) — standard practice for surface measurement, aggregation and gross-limit
  quality control.
- Campbell Scientific, **TOA5** table file format (LoggerNet / CRBasic documentation).
- Iowa Environmental Mesonet, **ASOS/AWOS** data archive — https://mesonet.agron.iastate.edu/request/download.phtml?network=BR__ASOS

---
*Generated for the UDESC extreme-events response project. Datasets and figures under
`datasets/`; code under `scripts/` and `notebooks/`.*
