# Findings — CPTEC-WRF spin-up study

Two parts: an **auto-generated status** block (paste the latest `outputs/findings_auto.md` here
each time the pipeline is re-run) and a **human decision record** below it. No lead hours are to
be trimmed from the dashboard until this file records a `READY` status **and** an explicit
decision.

---

## Auto-generated status — last run 2026-07-27

> Status: **PRELIMINARY** — need ≥ 20 runs AND ≥ 500 pairs (have **1** run, **0** pairs).
> Archive runs: **1** | lead-hour span in archive: **7..15 h**.
> Matched hourly precip pairs: **0** | temp pairs: **0**.
> Candidate spin-up window: **6 h**; settled reference: **13..24 h**.
>
> _No matched pairs to summarise yet (verdict: insufficient data). The daily GitHub Action
> appends one run per cycle; re-run this script as the archive and observations accumulate._

**Why 0 pairs right now (expected, not a bug):** the archive holds only the +7…+15 h sample run
(dated 2026-07-26), which (a) has **no leads < 7 h**, so it cannot show spin-up at all, and
(b) has **no overlapping station observations** (the hourly masters currently end ~2026-07-15).
Real pairs begin accumulating once the extended 0→72 h fetch runs daily via the GitHub Action and
the observation masters advance to those dates.

**Pipeline validity is already established** independently of data volume: `spinup_analysis.py
--selftest` recovers a *known injected* early under-forecast (early ME = −0.395 mm h⁻¹,
95 % CI −0.445…−0.350, vs settled +0.054; freq-bias 1.06 vs 1.33 → "signature present") and
rejects a null case. So when data arrive, the estimator is trusted.

---

## Human decision record

_(empty until the status reads READY)_

When `READY`, record here:
1. **Date span & sample** — first/last run, number of runs, number of matched precip/temp pairs,
   and season(s) covered.
2. **Precipitation verdict** — early-vs-settled ME (with CI) and wet-frequency bias; the per-lead
   `rain_ME` curve; the lead at which ME returns to the settled baseline.
3. **Decision** — trim leads `1..k` for **precipitation** (state `k`), or keep all leads; and the
   same for temperature (expected: keep all).
4. **How applied** — if trimming, where (frontend future-window floor, and/or `fetch_wrf.py`
   `--leads` lower bound), and confirmation it was applied.
5. **Caveats carried** — representativeness, truth error, regime coverage, and the still-open
   CPTEC data-assimilation question (which governs the mechanistic reading, not the decision).

## Expected outcomes (hypotheses on record, to be confirmed or refuted)

- **If CPTEC AMS 7 km is a GFS cold-start downscaling:** expect a measurable precip under-forecast
  in leads ~1–6 h (per Jerez 2020 / Liu 2023 / forum guidance and our own §B.3 estimate),
  recovering thereafter → trim a *small* precip window (likely ≤ 6 h), not 12 h, and not for
  temp/wind.
- **If it assimilates observations:** the early under-forecast may be weak or absent → keep all
  leads. Either way the data decide; this file will state which.

_Reminder: a blanket 12 h discard would throw away the most skillful near-term forecast. Trim only
what the measured signal justifies, only for the variable that shows it._
