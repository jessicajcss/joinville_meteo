# Lab log — CPTEC-WRF spin-up study

A dated, append-only record of the reasoning, literature review, and decisions behind this
study. Newest entries at the bottom. Epistemic tags as in METHODOLOGY.md.

---

## 2026-07-27 — Origin of the question

Prompt from the dashboard work: *"shouldn't we discard the first 12 h of the model? is it
already done? is it valid for these CPTEC data?"* — with an explicit instruction to find real,
peer-reviewed / INPE information and not to assume.

Decision to treat this as a **standalone verification study**, documented apart from the
dashboard, because (a) it is a scientific claim that must be auditable and citable on its own,
and (b) the answer changes an operational choice (trimming forecast hours) that affects every
Previsão page.

---

## 2026-07-27 — Literature review (what the sources actually say)

**Two different "spin-ups" — the key clarification.**

- **Land-surface / soil-moisture spin-up (does NOT apply to us).**
  *Examining spin-up behaviour within WRF dynamical downscaling applications*, Geoscientific
  Model Development (GMD) 19, 579-…, 2026 — finds RCM applications need **≥ 1 year** of spin-up,
  with **top-layer soil moisture needing 1–4 years**; warns 3 months is inadequate. This is for
  *continuous* climate downscaling that integrates the land surface over time. Our product is
  **re-initialised from GFS every cycle**, so nothing carries over — this multi-month figure is
  irrelevant here. Recorded specifically to *rule it out* (it is the number one is most likely to
  find and mis-apply).

- **Atmospheric / precipitation spin-up (DOES apply).**
  - *On the Spin-Up Period in WRF Simulations Over Europe: Trade-Offs Between Length and
    Seasonality*, Jerez, S., et al., **Journal of Advances in Modeling Earth Systems (JAMES)**
    12(4), e2019MS001945, 2020 — peer-reviewed treatment of spin-up length/seasonality trade-offs.
  - *Developing spin-up time framework for WRF extreme precipitation simulations*, **Liu, Y.,
    Zhuo, L., & Han, D., Journal of Hydrology 620, 129443, 2023** (DOI 10.1016/j.jhydrol.2023.
    129443) — proposes an "Optimal Spin-up Time Identifying (OSTI)" framework and finds the needed
    spin-up is **situation-dependent**: *"disturbing weather events strengthen the influence of
    initial conditions … and increase model requirements for spin-up time"*. **Takeaway: there is
    no universal constant** — which is exactly why we measure rather than assume.
  - WRF developers' support forum (NCAR/MMM), *"How do use model spin up for forecast data"* —
    common practical guidance is to **discard the first ~6 h** of output, with the caveat that the
    needed length depends on resolution/timestep (fine-resolution runs spin up faster). Community
    guidance, not peer-reviewed; cited as such.

**Project-internal corroboration.** `TUPANN_vs_WRF_methodology.md` §B.3 already states, for these
same CPTEC data, that spin-up is *"unreliable precipitation in roughly the first 1–6 h after
initialisation"* and, at 9–12 h lead, *"largely past."* It also §E **confirms** the from-init
accumulation convention for these files (`GRIB_stepType='accum'`, monotonic `tp`, 0 clipped
negatives), which our de-accumulation depends on.

**Where I stopped short (honest gaps).**
- Could **not** read the full text of Liu et al. 2023 (ScienceDirect robots-blocked) — so no
  specific hour count is quoted from it, only its framework/qualitative finding.
- Could **not** confirm whether **CPTEC's AMS 7 km** product uses **data assimilation**
  (GSI/3D-Var, which would shorten/remove cold-start spin-up) or is a plain GFS-initialised
  downscaling (which would show it). ResearchGate returned HTTP 429; the CPT-WRF v1.1 doc and INPE
  Eta publications page were located but not fully parsed. **This is an open item** (below). It
  does not block the empirical test — the data decide — but it governs the *mechanistic*
  interpretation.

**Conclusion of the review.** The relevant spin-up is the short atmospheric/precip one (~1–6 h,
possibly more in disturbed weather), it is **not** currently applied in our pipeline, and its
validity for these CPTEC data is an **empirical** question we can answer with the station network.

---

## 2026-07-27 — Design decisions

- **[Decision] Measure, don't assume.** Reject hard-coding "discard 12 h". Build a lead-stratified
  verification of the archived forecast against station obs; let the data set the cut (or show
  there isn't one). Rationale: Liu et al. (2023) — spin-up length is situation-dependent; and a
  blanket 12 h cut would discard the most skillful near-term hours, especially for temp/wind.
- **[Decision] Point verification, not gridded, for this question.** The spin-up signal is a
  systematic error vs lead; co-located gauge/cell pairs isolate it, whereas areal CSI/FSS blur it
  with representativeness/double-penalty. Reuse `verif_core` categorical *definitions* for
  consistency. (METHODOLOGY §2.3.)
- **[Decision] Early vs settled windows with a CI rule.** Early = leads 1..6; settled = 13..24.
  Signature = early ME 95 % CI upper bound below settled mean ME **and** lower early wet-frequency
  bias. Conservative on purpose to resist false positives in noisy hourly rain. (METHODOLOGY §5.)
- **[Decision] Readiness gate.** No verdict until ≥ 20 runs **and** ≥ 500 matched precip pairs;
  `PRELIMINARY` otherwise. Prevents over-reading early noise. (METHODOLOGY §6.)
- **[Decision] Thresholds for hourly accumulation.** Use 0.2/1/2/5 mm h⁻¹ (light→moderate hourly
  totals), following the `TUPANN_vs_WRF_methodology.md` §E note that the paper's 4–64 mm h⁻¹
  instantaneous-rate thresholds are inappropriate for hourly accumulation.
- **[Decision] Self-test first.** Embed a synthetic validation (inject a known early
  under-forecast; also a null) that must pass before trusting real output — mirrors
  `verif_core.py`'s unit-test discipline.

---

## 2026-07-27 — Build & validation

- Wrote `spinup_analysis.py` (standalone: numpy/pandas/matplotlib). Loaders for archive, station
  coords, and hourly obs; nearest-cell matching; per-lead metrics; early-vs-settled bootstrap
  test; plot; auto-written findings.
- **Self-test PASSED.** On synthetic data with an injected early under-forecast (early leads = 0.3×
  obs), the pipeline reports *"spin-up signature present"* with early ME = −0.395 mm h⁻¹
  (95 % CI −0.445…−0.350) vs settled +0.054, freq-bias 1.06 vs 1.33; on a null (no lead
  dependence) it reports *"no strong spin-up signature."* The estimator recovers a known signal
  and rejects a null.
- **Real-data run → PRELIMINARY, as expected.** Archive currently = **1 run** (the +7…+15 h
  sample), **0 matched pairs** (sample run date 2026-07-26 has no overlapping station obs, which
  end ~2026-07-15; and the sample has no leads < 7 anyway). Status correctly withheld.

---

## Open items / to-do

- **[OPEN — verify] CPTEC AMS 7 km data assimilation vs cold start.** Confirm from INPE/CPTEC
  documentation (CPT-WRF technical notes; INPE DMNST / Eta-model pages; WGNE center updates)
  whether the operational AMS 7 km run assimilates observations. Governs the *mechanistic*
  reading of any measured early bias. Sources to pursue in REFERENCES (INPE section).
- **[TO-DO] Re-run as the archive grows.** Re-execute after each ~week of daily runs; watch the
  status flip to `READY`. Ideally accumulate across dry- and wet-season regimes before concluding.
- **[TO-DO] Verify the `prec` accumulation convention** per logger (hourly total vs rate) before
  trusting precip pairs at `READY`.
- **[TO-DO] Track station QC.** Exclude the same sensors the dashboard excludes (e.g. Nova
  Brasília gauge; UDESC rain over-estimate) so the truth is clean.
- **[FUTURE] Independent truth cross-check.** Optionally repeat against IMERG hourly for the same
  cells to separate gauge under-catch from genuine forecast bias (cf. `TUPANN_vs_WRF_
  methodology.md` §B.4 on truth independence).
