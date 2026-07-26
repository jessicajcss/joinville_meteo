#!/usr/bin/env python3
"""
Rain quality control for the Joinville station masters — inch-based datalogger
error codes, physically impossible rates, and accumulation "catch-up" dumps.

WHY (diagnosis, from the station data itself):
  The tipping buckets are inch-based (tip resolution 0.254 mm = 0.01 in). Their
  fault/overflow code surfaces as an EXACT inch value in the rain field:
      254.0 mm = 10.00 in  — appears 1,092× across the hourly network (impossible
                             as real rain: >200 mm/h happens 1,146 h, but >254 only
                             a handful; the 99.9th AND 99.99th percentiles are both
                             exactly 254.0 — the signature of a sentinel, not weather).
      228.6 mm =  9.00 in  — the same code, 6×.
  (1 in = 25.4 mm and 2 in = 50.8 mm are KEPT — those are plausible real totals.)
  Above the code, two residual artefacts remain:
    * gross logger spikes (e.g. 1606.8, 961.8 mm in one hour) — physically impossible;
    * catch-up dumps — a large value in the hour right after a multi-hour data gap,
      i.e. rain that fell over the missing hours reported in one bucket
      (e.g. 488 mm after a 2,710 h gap, 142 mm after 1,953 h).

RULE (flag, don't silently delete — the raw upstream files stay the audit trail,
      and every removed point is written to data/processed/rain_qc_flags.csv):
  1. inch_code : prec in {228.6, 254.0}                      -> flag
  2. ceiling   : prec > HOURLY_CEIL (150 mm/h) / DAILY_CEIL (350 mm/d) -> flag
                 (the observed data have a clean empty gap between credible
                  storm-embedded values, ≤~115 mm/h, and the instrument shelf,
                  ≥~229 mm/h; 150 sits in that gap and exceeds documented
                  sub-hourly rainfall extremes for southern Brazil.)
  3. gap_dump  : (hourly only) value ≥ DUMP_MIN right after a > GAP_H data gap -> flag
Flagged points are set to NaN (missing, not 0 — 0 would bias totals low; NaN is
excluded by the existing ≥N-valid-day/hour coverage thresholds).

Verified on the real masters: max KEPT hourly rate per station 48–115 mm/h (all
physical); 1,152/825,681 hourly points flagged (0.14%).
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd

INCH_CODES = (228.6, 254.0)     # 9 in, 10 in — inch-based logger error/overflow codes
HOURLY_CEIL = 150.0             # mm h^-1  — physical plausibility ceiling
DAILY_CEIL = 350.0              # mm day^-1 — above credible regional daily extremes
GAP_H = 2.0                     # h — a gap this large means ≥1 missing hour
DUMP_MIN = 40.0                 # mm — a large value right after a gap = accumulation dump


def flag_rain(dates, prec, kind: str = "hourly") -> pd.Series:
    """Return a Series of flag reasons ('inch_code'|'ceiling'|'gap_dump'), NaN where clean.
    Aligned to the INPUT order; the gap test uses temporal order internally so the
    caller does NOT need to pre-sort (row order is preserved)."""
    x = pd.to_numeric(pd.Series(prec).reset_index(drop=True), errors="coerce")
    reason = pd.Series([pd.NA] * len(x), dtype=object)
    reason[x.isin(INCH_CODES)] = "inch_code"
    ceil = HOURLY_CEIL if kind == "hourly" else DAILY_CEIL
    reason[reason.isna() & (x > ceil)] = "ceiling"
    if kind == "hourly":
        d = pd.to_datetime(pd.Series(dates).reset_index(drop=True), errors="coerce")
        order = d.sort_values(kind="stable").index                   # temporal order
        gap = d.loc[order].diff().dt.total_seconds() / 3600.0         # gap-before, indexed by orig row
        gap = gap.reindex(range(len(x)))                             # back to original positions
        reason[reason.isna() & (gap > GAP_H) & (x >= DUMP_MIN)] = "gap_dump"
    return reason


def clean_master(path: Path, kind: str, station: str, audit: list) -> dict:
    """Flag the `prec` column of one master (csv + sibling parquet) in place, SURGICALLY:
    only flagged prec cells are blanked (→ NaN); every other cell is left byte-identical
    (the csv is round-tripped as strings, so full-precision floats are never re-serialised).
    Row order is preserved. Appends removed points to `audit`."""
    path = Path(path)
    if not path.exists():
        return {"station": station, "kind": kind, "n_flagged": 0}
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)         # exact strings, nothing coerced
    if "prec" not in raw.columns:
        return {"station": station, "kind": kind, "n_flagged": 0}
    reason = flag_rain(raw["date"], raw["prec"], kind)
    bad = reason.notna().values
    n = int(bad.sum())
    if n:
        raw_prec = pd.to_numeric(raw["prec"], errors="coerce")
        for i in np.where(bad)[0]:
            audit.append({"station": station, "kind": kind, "date": raw["date"].iloc[i],
                          "raw_prec": round(float(raw_prec.iloc[i]), 2), "reason": reason.iloc[i]})
        raw.loc[bad, "prec"] = ""                                     # blank = NaN downstream
        raw.to_csv(path, index=False)
        pq = path.with_suffix(".parquet")
        if pq.exists():
            try:
                dq = pd.read_parquet(pq)
                if "prec" in dq.columns:                              # flag the parquet on its OWN rows
                    rq = flag_rain(dq["date"], dq["prec"], kind)
                    dq.loc[rq.notna().values, "prec"] = np.nan
                    dq.to_parquet(pq, index=False)
            except Exception as e:
                print(f"[rain_qc] {station}: parquet not updated ({e})")
    by = reason[bad].value_counts().to_dict() if n else {}
    return {"station": station, "kind": kind, "n_flagged": n, "by_reason": by}


def clean_dir(data_dir: Path, report_dir: Path | None = None) -> pd.DataFrame:
    """Clean every hourly + daily station master under `data_dir/{hourly,daily}` and
    write the audit report (to `report_dir`, default `data_dir/processed`). Idempotent:
    re-running on already-clean masters flags nothing new. Safe to call at the end of
    build_hourly_daily.py and update_datasets.py so every rebuild/append stays clean."""
    data_dir = Path(data_dir)
    report_dir = Path(report_dir) if report_dir else (data_dir / "processed")
    audit: list = []
    summ = []
    for kind in ("hourly", "daily"):
        for p in sorted((data_dir / kind).glob("*.csv")):
            summ.append(clean_master(p, kind, p.stem, audit))
    # Merge with any existing report so the CUMULATIVE audit trail survives: a full rebuild
    # regenerates every flag; an incremental append adds only new ones — either way the
    # committed report keeps the whole history (the masters themselves no longer hold the raw
    # values once blanked, so this report is the record).
    report_dir.mkdir(parents=True, exist_ok=True)
    cols = ["station", "kind", "date", "raw_prec", "reason"]
    rep = pd.DataFrame(audit, columns=cols)
    fpath = report_dir / "rain_qc_flags.csv"
    if fpath.exists():
        try:
            prev = pd.read_csv(fpath)
            rep = pd.concat([prev, rep], ignore_index=True)
        except Exception:
            pass
    rep = rep.drop_duplicates(subset=["station", "kind", "date", "reason"]).sort_values(
        ["station", "kind", "date"])
    fpath.write_text(rep.to_csv(index=False) if len(rep) else
                     "station,kind,date,raw_prec,reason\n", encoding="utf-8")
    return pd.DataFrame(summ)


def clean_all(root: Path) -> pd.DataFrame:
    """Convenience: clean the masters under `root/data`."""
    return clean_dir(Path(root) / "data")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Flag inch-code / non-physical / catch-up rain in the station masters.")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args()
    s = clean_dir(Path(a.root) / "data")
    tot = int(s["n_flagged"].sum()) if len(s) else 0
    print(f"[rain_qc] flagged {tot} points across {len(s)} masters")
    for _, r in s.iterrows():
        if r.get("n_flagged"):
            print(f"    {r['station']:13} {r['kind']:6} {r['n_flagged']:5d}  {r.get('by_reason',{})}")
    print("[rain_qc] audit -> data/processed/rain_qc_flags.csv")
