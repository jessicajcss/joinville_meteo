#!/usr/bin/env python3
"""
spinup_analysis.py — empirical test for CPTEC-WRF (AMS 7 km) precipitation/temperature
spin-up over Joinville, by verifying the archived forecast against the station network,
stratified by forecast lead hour.

WHAT IT ANSWERS
    "Do the earliest forecast lead hours (the model 'spin-up' period) carry a systematic
     error — e.g. a precipitation under-forecast — that would justify discarding them,
     and if so, out to how many hours?"  We MEASURE it rather than assume a rule of thumb.

WHY (scientific basis — see REFERENCES.md for full citations)
    A limited-area model started from a coarser analysis (here GFS) is not in fine-scale
    dynamical/microphysical balance at t=0; it takes a few hours to grow its own clouds and
    precipitation, so early-lead rainfall is often under-produced (Jerez et al. 2020, JAMES;
    Liu et al. 2023, J. Hydrology — who show the needed length is situation-dependent, not a
    universal constant). The WRF developers' support forum commonly suggests discarding the
    first ~6 h. Note this is the SHORT atmospheric/precipitation spin-up — NOT the multi-month
    land-surface/soil-moisture spin-up of continuous climate downscaling, which does not apply
    to a product re-initialised from GFS every cycle. Our own project methodology note
    (TUPANN_vs_WRF_methodology.md, §B.3) already put the atmospheric spin-up at "roughly the
    first 1-6 h"; this script is the empirical check of that statement for these CPTEC data.

METHOD (summary; full detail in METHODOLOGY.md)
    * Forecast: site/data/wrf_grid_archive.csv — every archived run's ~7 km cells, HOURLY,
      one row per (run_time, valid_time[local UTC-3], lead_h, cell). rain_mm_h is already
      de-accumulated from the from-init GRIB accumulation (verified: GRIB_stepType='accum',
      monotonic tp — see methodology note §E).
    * Truth: the station hourly masters (data/hourly/<code>.csv), columns include local-time
      `date`, hourly `prec` (mm) and `temp` (degC). Station coords from station_history.json.
    * Pairing: nearest WRF cell to each station; match on identical local valid timestamp.
    * Stratify every (station, run, valid time) pair by lead_h and compute, per lead:
        - precipitation: N, mean error ME=mean(fcst-obs), MAE, RMSE, wet-frequency of
          forecast & obs, frequency BIAS, and POD/CSI at thresholds (defs = verif_core.py).
        - temperature: N, ME, MAE, RMSE.
    * Spin-up test: compare the early window (leads 1..S, default S=6) against a "settled"
      reference window (leads Rlo..Rhi, default 13..24) and report the ME/BIAS difference with
      a bootstrap 95% CI. A more-negative early precip ME + lower early frequency BIAS is the
      spin-up signature.

READINESS GATE
    Spin-up is a small systematic signal buried in very noisy hourly precipitation, so it only
    emerges over many runs. The script REFUSES to call a result unless at least --min-runs
    distinct runs AND --min-pairs matched hourly pairs are present; otherwise it writes a
    clearly-labelled PRELIMINARY status. As of first authoring the archive holds 1 run — the
    framework is complete; findings populate as the daily GitHub Action appends runs.

OUTPUTS (written to --out-dir, default ./outputs)
    spinup_metrics_by_lead.csv   per-lead table (precip + temp)
    spinup_pairs.csv             the raw matched pairs (for auditing / re-analysis)
    spinup_by_lead.png           ME/MAE/frequency-bias vs lead, spin-up window shaded
    findings_auto.md             machine-written status + numbers, pasted into FINDINGS.md

USAGE
    python spinup_analysis.py                          # uses repo-relative defaults
    python spinup_analysis.py --spinup-window 6 --ref-window 13 24 --min-runs 20

This script is standalone (only numpy, pandas, matplotlib). The categorical-score definitions
are transcribed from verif_core.py (WWRP/WGNE / Jolliffe & Stephenson conventions) so results
are consistent with the project's TUPANN-vs-WRF verification.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------------
# categorical scores at a rain threshold — definitions identical to verif_core.py
# (a=hits, b=false alarms, c=misses, d=correct negatives). WWRP/WGNE; Jolliffe & Stephenson.
# ----------------------------------------------------------------------------------------
def contingency(fcst, obs, thr):
    f = np.asarray(fcst, float); o = np.asarray(obs, float)
    m = np.isfinite(f) & np.isfinite(o)
    F = f[m] >= thr; O = o[m] >= thr
    a = int(np.sum(F & O)); b = int(np.sum(F & ~O))
    c = int(np.sum(~F & O)); d = int(np.sum(~F & ~O))
    return a, b, c, d


def cat_scores(fcst, obs, thr):
    a, b, c, d = contingency(fcst, obs, thr)
    def sd(n, den): return float(n) / den if den > 0 else np.nan
    pod = sd(a, a + c)                         # probability of detection
    far = sd(b, a + b)                         # false-alarm ratio
    csi = sd(a, a + b + c)                     # critical success index
    bias = sd(a + b, a + c)                    # frequency bias
    return dict(POD=pod, FAR=far, CSI=csi, BIAS=bias, hits=a, obs_events=a + c, fcst_events=a + b)


# ----------------------------------------------------------------------------------------
# loaders
# ----------------------------------------------------------------------------------------
def load_stations(stations_json: Path) -> pd.DataFrame:
    d = json.loads(stations_json.read_text(encoding="utf-8"))
    rows = [{"code": s["code"], "name": s.get("name", s["code"]),
             "lat": float(s["lat"]), "lon": float(s["lon"]),
             "vars": s.get("vars", [])} for s in d.get("stations", [])]
    return pd.DataFrame(rows)


def load_archive(archive_csv: Path) -> pd.DataFrame:
    a = pd.read_csv(archive_csv)
    a["valid_time"] = pd.to_datetime(a["valid_time"])          # local (UTC-3), matches obs
    a["run_time"] = a["run_time"].astype(str)
    for col in ("rain_mm_h", "temp_degC", "lead_h", "lat", "lon"):
        if col in a:
            a[col] = pd.to_numeric(a[col], errors="coerce")
    return a


def nearest_cell(archive: pd.DataFrame, lat: float, lon: float):
    """Nearest archived grid cell (i,j) to a station, by squared degree distance
    with a cos(lat) correction (fine over this ~0.5 deg domain)."""
    cells = archive[["i", "j", "lat", "lon"]].drop_duplicates()
    coslat = np.cos(np.radians(lat))
    d2 = ((cells["lat"] - lat) ** 2) + (((cells["lon"] - lon) * coslat) ** 2)
    k = d2.idxmin()
    return int(cells.loc[k, "i"]), int(cells.loc[k, "j"])


def load_obs(hourly_dir: Path, code: str) -> pd.DataFrame | None:
    f = hourly_dir / f"{code}.csv"
    if not f.exists():
        return None
    o = pd.read_csv(f, usecols=lambda c: c in ("date", "prec", "temp"))
    if "date" not in o:
        return None
    o["date"] = pd.to_datetime(o["date"], errors="coerce")
    o = o.dropna(subset=["date"]).set_index("date")
    return o


# ----------------------------------------------------------------------------------------
# build the matched (station x run x valid-time) pair table, stratified by lead
# ----------------------------------------------------------------------------------------
def build_pairs(archive: pd.DataFrame, stations: pd.DataFrame, hourly_dir: Path) -> pd.DataFrame:
    recs = []
    for _, st in stations.iterrows():
        obs = load_obs(hourly_dir, st["code"])
        if obs is None or obs.empty:
            continue
        i, j = nearest_cell(archive, st["lat"], st["lon"])
        sub = archive[(archive["i"] == i) & (archive["j"] == j)].copy()
        if sub.empty:
            continue
        # obs at each forecast valid time (exact hourly timestamp match, local time)
        vt = sub["valid_time"]
        o_prec = obs["prec"].reindex(vt).to_numpy() if "prec" in obs else np.full(len(vt), np.nan)
        o_temp = obs["temp"].reindex(vt).to_numpy() if "temp" in obs else np.full(len(vt), np.nan)
        recs.append(pd.DataFrame({
            "code": st["code"], "run_time": sub["run_time"].to_numpy(),
            "valid_time": vt.to_numpy(), "lead_h": sub["lead_h"].to_numpy(),
            "fcst_rain": sub["rain_mm_h"].to_numpy(), "obs_rain": o_prec,
            "fcst_temp": sub["temp_degC"].to_numpy() if "temp_degC" in sub else np.nan,
            "obs_temp": o_temp,
        }))
    if not recs:
        return pd.DataFrame(columns=["code", "run_time", "valid_time", "lead_h",
                                     "fcst_rain", "obs_rain", "fcst_temp", "obs_temp"])
    return pd.concat(recs, ignore_index=True)


# ----------------------------------------------------------------------------------------
# per-lead metrics
# ----------------------------------------------------------------------------------------
def metrics_by_lead(pairs: pd.DataFrame, thresholds) -> pd.DataFrame:
    out = []
    for lead, g in pairs.groupby("lead_h"):
        rrow = {"lead_h": int(lead)}
        # precipitation
        pr = g.dropna(subset=["fcst_rain", "obs_rain"])
        rrow["n_rain"] = len(pr)
        if len(pr):
            err = pr["fcst_rain"] - pr["obs_rain"]
            rrow["rain_ME"] = float(err.mean())
            rrow["rain_MAE"] = float(err.abs().mean())
            rrow["rain_RMSE"] = float(np.sqrt((err ** 2).mean()))
            rrow["obs_wetfrac"] = float((pr["obs_rain"] >= thresholds[0]).mean())
            rrow["fcst_wetfrac"] = float((pr["fcst_rain"] >= thresholds[0]).mean())
            for thr in thresholds:
                s = cat_scores(pr["fcst_rain"], pr["obs_rain"], thr)
                tag = f"{thr:g}"
                rrow[f"POD@{tag}"] = s["POD"]; rrow[f"CSI@{tag}"] = s["CSI"]; rrow[f"BIAS@{tag}"] = s["BIAS"]
        # temperature
        te = g.dropna(subset=["fcst_temp", "obs_temp"])
        rrow["n_temp"] = len(te)
        if len(te):
            terr = te["fcst_temp"] - te["obs_temp"]
            rrow["temp_ME"] = float(terr.mean())
            rrow["temp_MAE"] = float(terr.abs().mean())
            rrow["temp_RMSE"] = float(np.sqrt((terr ** 2).mean()))
        out.append(rrow)
    return pd.DataFrame(out).sort_values("lead_h").reset_index(drop=True)


def _boot_ci(x, n=2000, seed=12345):
    """Bootstrap 95% CI of the mean (percentile method)."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n, len(x)))].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def spinup_test(pairs: pd.DataFrame, spinup_S: int, ref_lo: int, ref_hi: int, wet_thr: float):
    """Compare the early (spin-up) window vs a settled reference window for precip."""
    pr = pairs.dropna(subset=["fcst_rain", "obs_rain"]).copy()
    pr["err"] = pr["fcst_rain"] - pr["obs_rain"]
    early = pr[pr["lead_h"] <= spinup_S]
    ref = pr[(pr["lead_h"] >= ref_lo) & (pr["lead_h"] <= ref_hi)]

    def block(b):
        if not len(b):
            return dict(n=0, ME=np.nan, ME_lo=np.nan, ME_hi=np.nan, fcst_wet=np.nan, obs_wet=np.nan, bias=np.nan)
        lo, hi = _boot_ci(b["err"])
        fw = float((b["fcst_rain"] >= wet_thr).mean()); ow = float((b["obs_rain"] >= wet_thr).mean())
        return dict(n=int(len(b)), ME=float(b["err"].mean()), ME_lo=lo, ME_hi=hi,
                    fcst_wet=fw, obs_wet=ow, bias=(fw / ow if ow > 0 else np.nan))

    e, r = block(early), block(ref)
    verdict = "insufficient data"
    if e["n"] and r["n"] and np.isfinite(e["ME_hi"]) and np.isfinite(r["ME"]):
        # signature: the early window's 95% CI upper bound sits BELOW the settled mean error
        # (a statistically clear under-forecast), AND the early wet-frequency bias is lower.
        clearly_drier = (e["ME_hi"] < r["ME"]) and \
                        (np.isfinite(e["bias"]) and np.isfinite(r["bias"]) and e["bias"] < r["bias"])
        verdict = ("early leads under-forecast vs settled (spin-up signature present)"
                   if clearly_drier else
                   "no clear early under-forecast (no strong spin-up signature)")
    return {"spinup_window": f"1..{spinup_S} h", "ref_window": f"{ref_lo}..{ref_hi} h",
            "early": e, "settled": r, "verdict": verdict}


# ----------------------------------------------------------------------------------------
# plot
# ----------------------------------------------------------------------------------------
def _series(ax, m, col, **kw):
    """Plot m[col] vs lead only if the column exists and has finite values. Returns True if drawn."""
    if col in m.columns and pd.to_numeric(m[col], errors="coerce").notna().any():
        ax.plot(m["lead_h"], pd.to_numeric(m[col], errors="coerce"), "-o", ms=3, **kw)
        return True
    return False


def make_plot(m: pd.DataFrame, spinup_S: int, out_png: Path, wet_thr: float):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, 1, figsize=(8.5, 9), sharex=True)
    ax[0].axhline(0, color="#999", lw=0.8)
    d0 = _series(ax[0], m, "rain_ME", color="#2166ac", label="rain ME (fcst-obs)")
    _series(ax[0], m, "rain_MAE", color="#8a8f98", label="rain MAE")
    ax[0].set_ylabel("mm h$^{-1}$"); ax[0].set_title("Precipitation error by forecast lead")
    if d0:
        ax[0].legend(fontsize=8)
    ax[1].axhline(1, color="#999", lw=0.8)
    _series(ax[1], m, f"BIAS@{wet_thr:g}", color="#6a51a3")
    ax[1].set_ylabel(f"freq. bias @{wet_thr:g} mm"); ax[1].set_title("Wet-frequency bias by lead (1 = unbiased)")
    ax[2].axhline(0, color="#999", lw=0.8)
    d2 = _series(ax[2], m, "temp_ME", color="#d6604d", label="temp ME")
    _series(ax[2], m, "temp_MAE", color="#8a8f98", label="temp MAE")
    ax[2].set_ylabel("degC"); ax[2].set_title("2-m temperature error by lead")
    ax[2].set_xlabel("forecast lead (hours from initialisation)")
    if d2:
        ax[2].legend(fontsize=8)
    for a in ax:
        a.axvspan(0.5, spinup_S + 0.5, color="#ffd27f", alpha=0.30)   # candidate spin-up window
        a.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)


# ----------------------------------------------------------------------------------------
# self-test — validates the analysis end-to-end on SYNTHETIC data with a known answer,
# so the math is trusted before real runs accumulate (mirrors verif_core.py's unit tests).
# ----------------------------------------------------------------------------------------
def selftest():
    rng = np.random.default_rng(0)

    def synth(factor):
        rows = []
        for run in range(60):                          # 60 runs
            for lead in range(1, 25):                  # leads 1..24 h
                for _ in range(6):                     # 6 stations
                    obs = max(0.0, rng.gamma(0.3, 3.0) - 0.5)   # intermittent rain, many dry hours
                    f = max(0.0, factor(lead) * obs + rng.normal(0, 0.2))
                    rows.append((f"r{run}", lead, f, obs))
        df = pd.DataFrame(rows, columns=["run_time", "lead_h", "fcst_rain", "obs_rain"])
        df["fcst_temp"] = np.nan; df["obs_temp"] = np.nan
        return df

    A = synth(lambda L: 0.3 if L <= 6 else 1.0)        # injected: early leads under-forecast
    tA = spinup_test(A, 6, 13, 24, 0.2)
    assert tA["early"]["ME"] < tA["settled"]["ME"], "A: early should under-forecast"
    assert "signature present" in tA["verdict"], f"A verdict wrong: {tA['verdict']}"

    B = synth(lambda L: 1.0)                           # null: no lead dependence
    tB = spinup_test(B, 6, 13, 24, 0.2)
    assert "no strong" in tB["verdict"], f"B verdict wrong: {tB['verdict']}"

    mA = metrics_by_lead(A, [0.2, 1, 2])
    assert mA["rain_ME"].iloc[0] < mA["rain_ME"].iloc[-1], "A: lead-1 ME should be below lead-24 ME"

    print(f"[selftest] A (injected spin-up): {tA['verdict']}")
    print(f"           early ME={tA['early']['ME']:.3f} (CI {tA['early']['ME_lo']:.3f}..{tA['early']['ME_hi']:.3f}) "
          f"vs settled ME={tA['settled']['ME']:.3f}; freq-bias {tA['early']['bias']:.2f} vs {tA['settled']['bias']:.2f}")
    print(f"[selftest] B (null): {tB['verdict']}  (early ME={tB['early']['ME']:.3f} vs settled {tB['settled']['ME']:.3f})")
    print("[selftest] PASSED ✅  — analysis correctly finds an injected signal and rejects a null.")
    return 0


def main():
    here = Path(__file__).resolve().parent
    repo = here.parent
    ap = argparse.ArgumentParser(description="CPTEC-WRF spin-up test by forecast lead vs station obs")
    ap.add_argument("--archive", default=str(repo / "site/data/wrf_grid_archive.csv"))
    ap.add_argument("--stations", default=str(repo / "site/data/station_history.json"))
    ap.add_argument("--obs-dir", default=str(repo / "data/hourly"))
    ap.add_argument("--out-dir", default=str(here / "outputs"))
    ap.add_argument("--thresholds", default="0.2,1,2,5", help="precip thresholds (mm h-1)")
    ap.add_argument("--spinup-window", type=int, default=6, help="early window leads 1..S")
    ap.add_argument("--ref-window", type=int, nargs=2, default=[13, 24], help="settled reference leads lo hi")
    ap.add_argument("--min-runs", type=int, default=20, help="distinct runs required to report a verdict")
    ap.add_argument("--min-pairs", type=int, default=500, help="matched precip pairs required to report a verdict")
    ap.add_argument("--selftest", action="store_true", help="run synthetic validation and exit")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    thresholds = [float(x) for x in a.thresholds.split(",")]
    out_dir = Path(a.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    archive_p, stations_p, obs_p = Path(a.archive), Path(a.stations), Path(a.obs_dir)

    for p in (archive_p, stations_p):
        if not p.exists():
            print(f"[spinup] missing input: {p}", file=sys.stderr); return 2
    if not obs_p.exists():
        print(f"[spinup] missing obs dir: {obs_p}", file=sys.stderr); return 2

    archive = load_archive(archive_p)
    stations = load_stations(stations_p)
    n_runs = archive["run_time"].nunique()
    lead_min, lead_max = int(archive["lead_h"].min()), int(archive["lead_h"].max())

    pairs = build_pairs(archive, stations, obs_p)
    n_pairs = int(pairs.dropna(subset=["fcst_rain", "obs_rain"]).shape[0])

    m = metrics_by_lead(pairs, thresholds) if len(pairs) else pd.DataFrame()
    test = spinup_test(pairs, a.spinup_window, a.ref_window[0], a.ref_window[1], thresholds[0]) \
        if len(pairs) else {"verdict": "no matched pairs yet"}

    ready = (n_runs >= a.min_runs) and (n_pairs >= a.min_pairs)
    status = "READY — verdict below is data-backed" if ready else \
             f"PRELIMINARY — need >= {a.min_runs} runs AND >= {a.min_pairs} pairs (have {n_runs} runs, {n_pairs} pairs)"

    # write outputs
    if len(m):
        m.to_csv(out_dir / "spinup_metrics_by_lead.csv", index=False)
        make_plot(m, a.spinup_window, out_dir / "spinup_by_lead.png", thresholds[0])
    if len(pairs):
        pairs.to_csv(out_dir / "spinup_pairs.csv", index=False)

    lines = []
    lines.append(f"# Spin-up test — auto-generated status\n")
    lines.append(f"- **Status:** {status}")
    lines.append(f"- Archive runs: **{n_runs}** | lead-hour span in archive: **{lead_min}..{lead_max} h**")
    lines.append(f"- Matched hourly precip pairs: **{n_pairs}** | temp pairs: "
                 f"**{int(pairs.dropna(subset=['fcst_temp','obs_temp']).shape[0]) if len(pairs) else 0}**")
    lines.append(f"- Candidate spin-up window: **{a.spinup_window} h**; settled reference: "
                 f"**{a.ref_window[0]}..{a.ref_window[1]} h**")
    lines.append("")
    if len(pairs) and isinstance(test.get("early"), dict) and test["early"]["n"]:
        e, r = test["early"], test["settled"]
        lines.append("## Precipitation early-vs-settled")
        lines.append(f"- Early (1..{a.spinup_window} h): n={e['n']}, "
                     f"ME={e['ME']:.3f} mm h⁻¹ (95% CI {e['ME_lo']:.3f}..{e['ME_hi']:.3f}), "
                     f"freq-bias@{thresholds[0]:g}={e['bias']:.2f}")
        lines.append(f"- Settled ({a.ref_window[0]}..{a.ref_window[1]} h): n={r['n']}, "
                     f"ME={r['ME']:.3f} mm h⁻¹ (95% CI {r['ME_lo']:.3f}..{r['ME_hi']:.3f}), "
                     f"freq-bias@{thresholds[0]:g}={r['bias']:.2f}")
        lines.append(f"- **Read:** {test['verdict']}")
    else:
        lines.append(f"_No matched pairs to summarise yet (verdict: {test.get('verdict')}). "
                     "The daily GitHub Action appends one run per cycle; re-run this script as the "
                     "archive and observations accumulate._")
    lines.append("")
    lines.append("> Interpretation guide and caveats: see METHODOLOGY.md §5 (a negative early ME with "
                 "freq-bias < 1, relative to the settled window, is the precipitation spin-up signature). "
                 "Do NOT trim leads on a PRELIMINARY status.")
    (out_dir / "findings_auto.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[spinup] wrote outputs to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
