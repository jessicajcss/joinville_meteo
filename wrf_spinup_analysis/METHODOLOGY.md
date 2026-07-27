# Methodology — CPTEC-WRF spin-up test by forecast lead

_Working methodology note (UDESC PostDoc, LaCiA/PPGEC). Companion to `spinup_analysis.py`,
`LAB_LOG.md`, and the project's `verif_core.py` and `TUPANN_vs_WRF_methodology.md`._

> **Epistemic status tags** (same convention as `TUPANN_vs_WRF_methodology.md`):
> **[Established]** = supported by cited peer-reviewed / official documentation;
> **[Must verify]** = an assumption to be checked against a data file or CPTEC documentation;
> **[Design choice]** = a methodological decision with stated trade-offs.
> Bibliographic details to be confirmed at the linked source (see `REFERENCES.md`).

---

## 1. Question and hypotheses

**Question.** For the CPTEC/INPE WRF AMS 7 km product over Joinville, do the earliest forecast
lead hours carry a systematic error attributable to model spin-up — and if so, out to how many
hours should they be discarded from the dashboard?

**H1 (precipitation spin-up).** [Established as a general phenomenon; Must verify for this product]
Because the model is initialised from a coarser GFS analysis and must grow its own fine-scale
moisture and precipitation, the earliest lead hours **under-forecast** rainfall. Predicted
signature: in leads 1..S the mean error `ME = mean(forecast − obs)` is negative and the
wet-frequency bias is < 1, both relative to a settled reference window, converging to the
settled baseline once spin-up completes.

**H0 (null).** No lead-dependent early bias: `ME(lead)` and wet-frequency bias are flat across
lead (within sampling noise) from lead 1 onward.

**Prior.** Literature and our own note put atmospheric/precip spin-up at **~1–6 h** (Jerez et
al. 2020; Liu et al. 2023 — situation-dependent; WRF support-forum ~6 h; `TUPANN_vs_WRF_
methodology.md` §B.3 "roughly the first 1–6 h"). So the default early window `S = 6 h` is a
hypothesis to test, **not** a value to hard-code before the test passes.

---

## 2. Data

### 2.1 Forecast — `site/data/wrf_grid_archive.csv` [Established for this project]
Append-only long-format archive written by `scripts/archive_wrf_grid.py`: one row per
`(run_time, valid_time, lead_h, cell i,j)` over the ~10×10 local ~7 km grid, hourly, with
`rain_mm_h, temp_degC, u10_ms, v10_ms, wind_ms, wind_dir_deg`.

- `rain_mm_h` is **already de-accumulated** in `fetch_wrf.py` from the GRIB from-init
  accumulation. [Established] The from-init convention was verified for these files in
  `TUPANN_vs_WRF_methodology.md` §E: `GRIB_stepType='accum'`, domain-mean `tp` monotonic,
  0 clipped negatives on differencing. (Re-affirm per product/version — encoding can change.)
- De-accumulation drops lead 0, so archived leads run **1..N** (N up to 72 after the fetch
  window was extended to 3 days). [Established] **Consequence:** the *current* archive, built
  from the +7…+15 h sample `.nc`, has **no leads < 7** and therefore cannot show spin-up at all;
  the test needs the new 0→72 h fetch's runs.
- Times are **local (UTC−3)**; `run_time` is the UTC cycle label (00Z / 12Z).

### 2.2 Truth — station hourly masters `data/hourly/<code>.csv` [Established]
Columns include local-time `date`, hourly `prec` (mm) and `temp` (°C) for 11 Joinville stations
(Defesa Civil / SEPROT network). Coordinates from `site/data/station_history.json`.
[Must verify per network] `prec` is taken to be the **hourly accumulation** (mm in the hour),
matching WRF's hourly accumulation; `temp` an instantaneous hourly reading matching WRF's
instantaneous `t2m`. If any logger reports a rate or a different accumulation window this must be
reconciled before trusting precip pairs.

### 2.3 Why point (station) verification here, not gridded [Design choice]
The project's gridded verification (`verif_core.py`: CSI/HSS/FSS on common grids) is the right
tool for a **spatial** forecast-vs-truth comparison over an area with a gridded truth (e.g.
IMERG/RRQPE). For a **spin-up** question the signal is a *systematic error vs lead*, best isolated
by pairing each WRF cell with a **co-located in-situ gauge/thermometer** and stratifying by lead;
gridded areal scores would blur the spin-up signal with representativeness and double-penalty
effects. Both approaches use the *same categorical definitions* (below) for consistency.

---

## 3. Matching procedure

- **Spatial** [Design choice]: each station is matched to its **nearest archived grid cell** by
  cos-lat-corrected degree distance. Over a ~0.5° domain of ~7 km cells this is adequate; the
  ~7 km representativeness gap (point gauge vs area-mean cell) is a known, documented limitation
  (§7), not removable by nearest-neighbour choice.
- **Temporal** [Design choice]: pair on the **identical local hourly timestamp** — the forecast
  valid time equals the observation time. Both are UTC−3, so no offset is applied; using
  `run_time`(UTC) + `lead_h` also reproduces the same instant. Exact-timestamp join (no
  tolerance window) avoids smearing hourly precipitation.
- **Stratification**: every matched `(station, run, valid_time)` pair carries its `lead_h`; all
  statistics are computed **within each lead**, then compared across leads.

Result: a tidy `spinup_pairs.csv` of `(code, run_time, valid_time, lead_h, fcst_rain, obs_rain,
fcst_temp, obs_temp)` — the auditable atom of the whole study.

---

## 4. Metrics [Established — definitions identical to `verif_core.py`]

Per lead:

**Continuous (precip and temp):** `ME = mean(f − o)` (sign matters — negative = under-forecast),
`MAE = mean|f − o|`, `RMSE = sqrt(mean((f − o)²))`.

**Categorical precip** at thresholds `t ∈ {0.2, 1, 2, 5} mm h⁻¹`, from the 2×2 table
(a = hits, b = false alarms, c = misses, d = correct negatives; WWRP/WGNE; Jolliffe &
Stephenson; Wilks):
`POD = a/(a+c)`, `FAR = b/(a+b)`, `CSI = a/(a+b+c)`, frequency `BIAS = (a+b)/(a+c)`.
The wet threshold 0.2 mm h⁻¹ defines a "rain hour". These match `verif_core.contingency` exactly
so numbers are comparable to the TUPANN-vs-WRF work.

**Uncertainty:** the early-vs-settled mean-error difference is bracketed by a **bootstrap 95 % CI**
(2000 resamples, percentile method) so any claim is backed by a spread, not a point value
(cf. `TUPANN_vs_WRF_methodology.md` §B.6).

---

## 5. Spin-up detection criterion [Design choice; statistically explicit]

Compare an **early window** (leads `1..S`, default S = 6) against a **settled reference window**
(leads `Rlo..Rhi`, default 13..24 — past any plausible spin-up, before skill decays much).

Declare a **precipitation spin-up signature present** iff **both**:
1. the early window's **ME 95 % CI upper bound < the settled window's mean ME** (a
   *statistically clear* under-forecast, not just a point difference), **and**
2. the early wet-frequency bias < the settled wet-frequency bias (the model rains on *fewer*
   hours early — the expected microphysical spin-up fingerprint).

If a signature is present on a `READY` status, the recommended cut is the **largest early lead at
which per-lead `rain_ME` is still below the settled baseline**; leads at/after recovery are kept.
If no signature, **keep all leads**. Temperature is examined identically but with no expectation
of a trim.

This two-part, CI-based rule is deliberately conservative: it resists false positives from the
heavy noise of intermittent hourly rain, at the cost of needing a decent sample (next section).

---

## 6. Readiness gate and statistical power [Established rationale]

Spin-up is a *small systematic* signal inside *very noisy, mostly-zero* hourly precipitation, so
a single run (or a handful) cannot resolve it — the CI would be enormous. The pipeline therefore
**refuses to declare a verdict** until both `--min-runs` (default 20) distinct runs **and**
`--min-pairs` (default 500) matched precip pairs are present, writing a `PRELIMINARY` status
otherwise. These thresholds are a starting point; power grows with the square root of the number
of independent rain hours, and rain is intermittent, so in practice **several weeks to a couple of
months** of daily runs (and ideally spanning both wet and dry regimes) will be needed for a
stable answer — consistent with Liu et al. (2023) finding spin-up length itself is
weather-situation dependent. Re-run the script periodically; the status flips to `READY`
automatically.

---

## 7. Threats to validity (carry into any conclusion)

1. **Representativeness gap** — a point gauge vs a ~7 km area-mean cell; a cell can legitimately
   differ from any one station, inflating error variance and possibly masking a small ME signal.
2. **Truth error** — gauge precipitation has its own under-catch (wind, tipping-bucket
   thresholds); the dashboard QC already excludes some sensors (e.g. Nova Brasília gauge; UDESC
   over-estimates rain). Station selection for this test should track those QC decisions.
3. **Hourly-accumulation assumption** for `prec` [Must verify per logger] — a rate-vs-accumulation
   mismatch would corrupt precip pairs (§2.2).
4. **Intermittency / low base rate** — most hours are dry; categorical scores at higher thresholds
   will be sparse early on and should be read with their `n`.
5. **Sampling / regime dependence** — a verdict from only dry-season runs may not hold in summer
   convective season; report the date span and, ideally, stratify by season.
6. **CPTEC configuration unknown** [Must verify — OPEN] — whether the AMS 7 km product runs data
   assimilation (which would *shorten or remove* cold-start spin-up) or is a plain GFS-initialised
   downscaling (which *would* show it) was **not** confirmable from public sources at authoring
   time (ResearchGate/ScienceDirect returned 429/robots blocks). The empirical result is decisive
   regardless, but the mechanism's interpretation depends on this. See LAB_LOG open items.
7. **De-accumulation dependence** — all precip conclusions inherit the from-init accumulation
   assumption (§2.1); re-affirm it if CPTEC changes the product.

---

## 8. Reproducibility

Deterministic given fixed inputs (bootstrap seeded). Standalone (`numpy`, `pandas`,
`matplotlib`). The synthetic self-test (`--selftest`) validates the estimator end-to-end
(recovers an injected early under-forecast; rejects a null) before any real-data run is trusted,
mirroring the unit-test discipline of `verif_core.py`.
