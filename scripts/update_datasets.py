#!/usr/bin/env python3
"""
Incremental weekly update.

Reads every new file dropped in  data/incoming/  and appends it into the correct
master under  datasets/{5min,hourly,daily}/<code>.{parquet,csv}  (and the rain-gauge
master), de-duplicating by timestamp and keeping the most complete record. Then it
recomputes the derived daily means for any station whose hourly data changed, and
refreshes the coverage figures.

This is what the GitHub Action runs. It is fully idempotent: re-dropping the same
file changes nothing. The heavy one-time historical baseline is built separately
(build_station.py / build_hourly_daily.py / the notebook); this script only grows it.

  python scripts/update_datasets.py --incoming data/incoming --datasets datasets

Accepted inputs in data/incoming/:
  * Campbell TOA5 .dat tables — routed by table type: *_5 -> 5min, *_HR -> hourly,
    *_DIARIA -> daily; station identified from the TOA5 header.
  * rain-gauge CSVs (wide: date + one column per gauge) -> gauge master.
"""
from __future__ import annotations
import argparse
import glob
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from toa5 import parse_dat, station_name, MAP_INST, MAP_DAILY   # noqa: E402
from build_udesc import is_ecowitt, process_paths, UDESC_CODE   # noqa: E402

# TOA5 station name (UPPER, alnum) -> our code
ALIASES = {
    "CEASA": "ceasa", "AGUASDEJOINVILLE": "aguasdejoi", "AGUAS": "aguasdejoi",
    "FLOTFLUX": "flotflux", "FLOT_FLUX": "flotflux", "IATECLUBE": "iateclube",
    "IATCLUB": "iateclube", "IATECLUBE ": "iateclube", "CUBATAO": "cubatao",
    "ITAUM": "itaum", "ESTR_SUL": "rodovia", "ESTRSUL": "rodovia",
    "GUANABARA": "guanabara", "DIVOBRAS": "divobras", "PARAISO": "jardimparaiso",
    "J_PARAISO": "jardimparaiso", "JPARAISO": "jardimparaiso",
}
STD5 = ["date", "temp", "umid", "prec", "ws", "wd", "gust", "gust_dir", "solar",
        "pressure", "dewpoint", "heat_index", "wind_chill", "level", "level_max", "level_min"]
DCOLS = ["date", "temp_max", "temp_min", "umid_max", "umid_min", "solar_total",
         "gust_max", "gust_dir", "prec", "level_max", "level_min",
         "dewpoint", "heat_index", "wind_chill"]
FLOOR = {"5min": "5min", "hourly": "h", "daily": "D"}


def code_for(name: str):
    key = "".join(ch for ch in name.upper() if ch.isalnum() or ch == "_")
    return ALIASES.get(key) or ALIASES.get(key.replace("_", ""))


def table_kind(path: Path):
    """5min / hourly / daily from the TOA5 table name (header line 1, last field)."""
    with open(path, "r", encoding="latin-1") as fh:
        first = fh.readline()
    tbl = [p.strip().strip('"') for p in first.split(",")][-1].upper()
    if tbl.endswith("_5") or tbl.endswith("HIDRO_5"):
        return "5min"
    if tbl.endswith("_HR"):
        return "hourly"
    if tbl.endswith("_DIARIA"):
        return "daily"
    return None


def dedup(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df:
            df[c] = np.nan
    df = df[cols].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["_n"] = df.drop(columns=["date"]).notna().sum(axis=1)
    return (df.sort_values(["date", "_n"], ascending=[True, False])
            .drop_duplicates("date", keep="first").drop(columns="_n").reset_index(drop=True))


def read_master(fp: Path) -> pd.DataFrame:
    if fp.with_suffix(".parquet").exists():
        return pd.read_parquet(fp.with_suffix(".parquet"))
    if fp.with_suffix(".csv").exists():
        return pd.read_csv(fp.with_suffix(".csv"), parse_dates=["date"])
    return pd.DataFrame()


def write_master(df: pd.DataFrame, fp: Path) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(fp.with_suffix(".csv"), index=False)
    try:
        df.to_parquet(fp.with_suffix(".parquet"), index=False)
    except Exception:
        pass


def append(res: str, code: str, new: pd.DataFrame, ds: Path) -> None:
    cols = DCOLS if res == "daily" else STD5
    new = new.copy()
    new["date"] = pd.to_datetime(new["date"]).dt.floor(FLOOR[res])
    fp = ds / res / code
    merged = dedup(pd.concat([read_master(fp), new], ignore_index=True), cols)
    merged = merged[["date"] + [c for c in cols if c != "date" and merged[c].notna().any()]]
    write_master(merged, fp)
    print(f"  {res}/{code}: +{len(new):,} rows -> {len(merged):,} total "
          f"({str(merged['date'].min())[:10]}..{str(merged['date'].max())[:10]})")


def recompute_daily_means(code: str, ds: Path) -> None:
    hp = ds / "hourly" / code
    h = read_master(hp)
    if not len(h):
        return
    h["date"] = pd.to_datetime(h["date"])
    hh = h.assign(day=h["date"].dt.floor("D"))
    agg = {f"{s}_mean": (s, "mean") for s in ("temp", "umid", "ws", "pressure", "solar") if s in hh}
    means = hh.groupby("day").agg(n_hours=("date", "size"), **agg).reset_index().rename(columns={"day": "date"})
    d = read_master(ds / "daily" / code)
    if not len(d):
        d = means
    else:
        d["date"] = pd.to_datetime(d["date"])
        d = d.drop(columns=[c for c in d.columns if c.endswith("_mean") or c == "n_hours"], errors="ignore")
        d = d.merge(means, on="date", how="outer")
    write_master(d.sort_values("date").reset_index(drop=True), ds / "daily" / code)


def update_gauges(csv: Path, ds: Path) -> None:
    new = pd.read_csv(csv)
    # gauge files mix date-only and datetime rows -> ISO8601 parses both (avoids the
    # single-format-inference trap that would NaT every timestamped row)
    new["date"] = pd.to_datetime(new["date"], format="ISO8601", errors="coerce")
    new = new.dropna(subset=["date"])
    fp = ds / "gauges"
    old = read_master(fp)
    merged = pd.concat([old, new], ignore_index=True) if len(old) else new
    merged = (merged.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True))
    write_master(merged, fp)
    print(f"  gauges: +{len(new):,} rows -> {len(merged):,} total")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--incoming", default="data/incoming")
    ap.add_argument("--datasets", default="data")
    ap.add_argument("--figs", default="data/figs")
    a = ap.parse_args()
    inc, ds = Path(a.incoming), Path(a.datasets)
    touched_hourly = set()

    dats = sorted(glob.glob(str(inc / "**" / "*.dat"), recursive=True))
    for f in dats:
        p = Path(f)
        try:
            code = code_for(station_name(p))
            kind = table_kind(p)
        except Exception as e:
            print(f"  ! {p.name}: unreadable ({e})"); continue
        if not code or not kind:
            print(f"  ? {p.name}: unmapped station/table, skipped"); continue
        df = parse_dat(p, MAP_DAILY if kind == "daily" else MAP_INST)
        append(kind, code, df, ds)
        if kind == "hourly":
            touched_hourly.add(code)

    # CSV drops: Ecowitt/UDESC console exports -> udesc masters; gauge wide-CSVs -> gauge master
    csvs = sorted(set(glob.glob(str(inc / "**" / "*.csv"), recursive=True) +
                      glob.glob(str(inc / "**" / "*.CSV"), recursive=True)))
    ecowitt = [c for c in csvs if is_ecowitt(c)]
    if ecowitt:
        hourly, daily = process_paths(ecowitt)
        append("hourly", UDESC_CODE, hourly, ds)
        append("daily", UDESC_CODE, daily, ds)
        touched_hourly.add(UDESC_CODE)
        print(f"  ecowitt/{UDESC_CODE}: processed {len(ecowitt)} file(s)")
    for csv in csvs:
        if csv in ecowitt:
            continue
        low = os.path.basename(csv).lower()
        if "pluvi" in low or "gauge" in low or "chuva" in low:
            update_gauges(Path(csv), ds)

    for code in sorted(touched_hourly):
        recompute_daily_means(code, ds)
        print(f"  daily means recomputed: {code}")

    # rain QC on the (now-appended) masters — flag inch-code / non-physical / catch-up dumps
    try:
        from rain_qc import clean_dir
        qc = clean_dir(ds)
        print(f"  rain QC: flagged {int(qc['n_flagged'].sum()) if len(qc) else 0} points "
              f"-> {ds / 'processed' / 'rain_qc_flags.csv'}")
    except Exception as e:
        print(f"  (rain QC skipped: {e})")

    # refresh coverage figures
    try:
        from plot_coverage import coverage_table, coverage_heatmap, PER_DAY
        Path(a.figs).mkdir(parents=True, exist_ok=True)
        for tier, per in (("5min", 288), ("hourly", 24), ("daily", 1)):
            d = ds / tier
            if d.is_dir():
                cov = coverage_table(str(d), per)
                coverage_heatmap(cov, f"Cobertura — série {tier}", str(Path(a.figs) / f"coverage_{tier}.png"))
        print("  coverage figures refreshed")
    except Exception as e:
        print(f"  (figures skipped: {e})")

    print("update complete.")


if __name__ == "__main__":
    main()
