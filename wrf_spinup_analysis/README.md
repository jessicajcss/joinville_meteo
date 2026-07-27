# CPTEC-WRF spin-up analysis (Joinville)

**Purpose.** Decide, *from data rather than a rule of thumb*, whether the earliest forecast
lead hours of the CPTEC/INPE WRF (AMS 7 km) product carry a systematic error — most plausibly
a **precipitation under-forecast during model spin-up** — large enough to justify discarding
them from the Joinville dashboard, and if so, **out to how many hours**.

This folder is **self-contained and separate from the dashboard documentation** on purpose: it
is a small verification study with its own pipeline, methodology, lab log, references and
findings, so its conclusions can be audited and cited independently of the operational site.

> **One-line answer to the motivating question:** *not yet* — the archive currently holds a
> single run, which is far too little to measure a small systematic signal in very noisy
> hourly precipitation. The **framework is complete and self-validated**; the verdict fills in
> automatically as the daily GitHub Action appends runs. **Do not trim any lead hours until the
> status in `FINDINGS.md` reads `READY`.** (See METHODOLOGY §6 and LAB_LOG 2026-07-27.)

---

## What "spin-up" means here (and what it does *not*)

There are two distinct phenomena called *spin-up*; only one is relevant to an operational
forecast, and conflating them is the main trap.

1. **Atmospheric / precipitation spin-up (relevant).** A limited-area model started from a
   coarser analysis (here NCEP **GFS**) is not in fine-scale dynamical and microphysical
   balance at *t = 0*. It needs a few hours to grow its own clouds and precipitation, so the
   earliest lead hours often *under-produce* rain. Literature places this at roughly the first
   **1–6 h** (situation-dependent, longer for disturbed weather) — see REFERENCES:
   Jerez et al. 2020 (JAMES); Liu et al. 2023 (J. Hydrology); WRF support-forum guidance
   (~6 h). Our own project note `TUPANN_vs_WRF_methodology.md` §B.3 independently estimated
   *"roughly the first 1–6 h"*. **This study measures it for these CPTEC data.**

2. **Land-surface / soil-moisture spin-up (NOT relevant here).** Continuous climate/downscaling
   runs need **months to years** for soil moisture to equilibrate (e.g. GMD 2026 downscaling
   study: ≥ 1 year; soil moisture 1–4 years). This does **not** apply to a product that is
   **re-initialised from GFS every cycle** — nothing carries over between runs. Discarding
   *days* would be wrong.

**Tension to keep in mind:** the early hours are also the *most skillful* part of any forecast,
so trimming them throws away the best near-term data — especially for temperature and wind,
which settle faster than precipitation. Trim only what the data show is biased, and only for the
variable that shows it.

---

## Quick start

```bash
# from this folder (needs: python3, numpy, pandas, matplotlib)
python spinup_analysis.py --selftest      # synthetic validation, no data needed — must print PASSED
python spinup_analysis.py                 # run against the real archive + station obs
```

Defaults resolve paths relative to the repository root (the parent of this folder):

| input | default path | what it is |
|---|---|---|
| forecast archive | `site/data/wrf_grid_archive.csv` | every run's ~7 km cells, hourly, with `lead_h` |
| station coords | `site/data/station_history.json` | station `code, name, lat, lon, vars` |
| observations | `data/hourly/<code>.csv` | hourly `date, prec, temp` (local UTC−3) |

Useful flags: `--spinup-window 6` (early window = leads 1..S), `--ref-window 13 24`
(settled reference), `--thresholds 0.2,1,2,5` (mm h⁻¹), `--min-runs 20 --min-pairs 500`
(readiness gate before a verdict is declared).

## Outputs (`outputs/`)

| file | contents |
|---|---|
| `spinup_metrics_by_lead.csv` | per-lead table: N, ME, MAE, RMSE, wet-frequencies, POD/CSI/BIAS(precip); ME/MAE/RMSE(temp) |
| `spinup_pairs.csv` | the raw matched (station × run × valid-time) pairs, for auditing / re-analysis |
| `spinup_by_lead.png` | ME/MAE, wet-frequency bias, and temperature error vs lead; candidate spin-up window shaded |
| `findings_auto.md` | machine-written status + numbers; its text is mirrored into `FINDINGS.md` |

## How to read the result

The **precipitation spin-up signature** is: in the early window (leads 1..S), the mean error
`ME = mean(forecast − obs)` is **clearly negative** (its bootstrap 95 % CI upper bound sits
below the settled window's mean error) **and** the wet-frequency bias is **< the settled
window's**. If both hold on a `READY` status, trim leads up to where ME returns to the settled
baseline. If they do not, keep all leads. Temperature is reported the same way (ME/MAE by lead)
but is not expected to need trimming.

## Files in this folder

```
wrf_spinup_analysis/
├── README.md          — this file (overview, quick start, how to read results)
├── METHODOLOGY.md     — full scientific method, hypotheses, stats, matching, threats to validity
├── LAB_LOG.md         — dated decision log + literature review + rationale
├── FINDINGS.md        — status + results (auto-updated section + human interpretation)
├── REFERENCES.md      — full bibliography (peer-reviewed + INPE/CPTEC + project-internal)
├── spinup_analysis.py — the pipeline (standalone; embeds a synthetic self-test)
└── outputs/           — generated artefacts (CSV, PNG, findings_auto.md)
```

## Status & provenance

Authored 2026-07-27 (UDESC PostDoc, LaCiA/PPGEC). Metric definitions are transcribed from the
project's `verif_core.py` (WWRP/WGNE conventions) so results are consistent with the existing
TUPANN-vs-WRF verification. The pipeline is validated by an embedded synthetic self-test that
must recover a known injected signal and reject a null before the real analysis is trusted.
