#!/usr/bin/env python3
"""
Consolidate ALL scattered/duplicated meteo sources into ONE clean master file
per station — the historical baseline that weekly .dat uploads then append to.

For each station it merges, then de-duplicates by timestamp (keeping the most
complete record):
  * the legacy  <code>_raw.csv        (already-clean 5-min history, 2012-~2020)
  * every TOA5  *_5.dat               (5-min tables: full-history dumps in
    meteo_add/, dated dump folders, and the current rolling tables in
    defesa_civil/) — found anywhere under the meteo root, so replication across
    folders collapses automatically.

Output: data/stations/<code>.csv (+ .parquet), unified schema, local time,
wind in m/s, extra variables (solar, pressure, gust, river level…) preserved.

Usage:
  python scripts/consolidate.py --meteo <meteo_root> --out data/stations [--only ceasa]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_dat import parse_toa5, station_name          # noqa: E402

# TOA5 station name (UPPER, non-alnum stripped) -> our station code.
# >>> CONFIRM/EDIT THIS MAP <<<  (esp. ESTR_SUL->rodovia and the hydro stations)
STATION_ALIASES = {
    "CEASA": "ceasa",
    "AGUASDEJOINVILLE": "aguasdejoi", "AGUAS": "aguasdejoi",
    "FLOTFLUX": "flotflux", "FLOT_FLUX": "flotflux",
    "IATECLUBE": "iateclube", "IATCLUB": "iateclube",
    "CUBATAO": "cubatao",
    "ITAUM": "itaum",
    "ESTR_SUL": "rodovia", "ESTRADA_SUL": "rodovia", "ESTRSUL": "rodovia",
    # hydro / rain-level stations (no temp/wind) — include as rain+level:
    "GUANABARA": "guanabara",
    "DIVOBRAS": "divobras",
    "PARAISO": "jardimparaiso", "J_PARAISO": "jardimparaiso", "JPARAISO": "jardimparaiso",
    "JATIVOCA": "jativoca",
}
STD_COLS = ["date", "temp", "umid", "prec", "ws", "wd", "gust", "gust_dir",
            "solar", "pressure", "dewpoint", "heat_index", "wind_chill",
            "level", "level_max", "level_min"]


def code_for(name: str) -> str | None:
    key = "".join(ch for ch in name.upper() if ch.isalnum() or ch == "_")
    return STATION_ALIASES.get(key) or STATION_ALIASES.get(key.replace("_", ""))


def load_legacy_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(
        "America/Sao_Paulo").dt.tz_localize(None)
    return df.dropna(subset=["date"])


def merge_dedup(frames: list[pd.DataFrame]) -> pd.DataFrame:
    df = pd.concat(frames, ignore_index=True)
    for c in STD_COLS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[STD_COLS]
    df["date"] = pd.to_datetime(df["date"])
    # keep the most complete row per timestamp
    df["_n"] = df.drop(columns=["date"]).notna().sum(axis=1)
    df = (df.sort_values(["date", "_n"], ascending=[True, False])
            .drop_duplicates("date", keep="first")
            .drop(columns="_n")
            .reset_index(drop=True))
    return df


def discover_dat(meteo_root: Path) -> list[Path]:
    """All 5-minute TOA5 tables anywhere under the meteo root."""
    out = []
    for p in meteo_root.rglob("*.dat"):
        stem = p.stem.upper()
        if stem.endswith("_5") or stem.endswith("HIDRO_5"):
            out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meteo", required=True)
    ap.add_argument("--out", default="data/stations")
    ap.add_argument("--only", default=None, help="limit to one station code")
    args = ap.parse_args()
    meteo = Path(args.meteo)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # bucket sources by station code
    buckets: dict[str, list[pd.DataFrame]] = {}
    unmapped: set[str] = set()

    # legacy csvs at meteo root
    for csv in meteo.glob("*_raw.csv"):
        code = csv.stem.replace("_raw", "")
        if code in ("pluviometros",):        # rain gauges handled separately
            continue
        if args.only and code != args.only:
            continue
        try:
            buckets.setdefault(code, []).append(load_legacy_csv(csv))
            print(f"[legacy] {csv.name} -> {code}")
        except Exception as e:
            print(f"[legacy] FAILED {csv.name}: {e}")

    # all 5-min .dat
    for dat in discover_dat(meteo):
        try:
            code = code_for(station_name(dat))
        except Exception:
            code = None
        if code is None:
            unmapped.add(dat.name); continue
        if args.only and code != args.only:
            continue
        try:
            buckets.setdefault(code, []).append(parse_toa5(dat))
        except Exception as e:
            print(f"[dat] FAILED {dat.name}: {e}")

    # merge + write
    summary = []
    for code, frames in sorted(buckets.items()):
        m = merge_dedup(frames)
        m.to_csv(out / f"{code}.csv", index=False)
        try:
            m.to_parquet(out / f"{code}.parquet", index=False)
        except Exception:
            pass
        cov = [c for c in STD_COLS if c != "date" and m[c].notna().any()]
        summary.append((code, len(m), str(m["date"].min())[:10], str(m["date"].max())[:10], cov))
        print(f"[master] {code:14s} {len(m):>9,} rows  {str(m['date'].min())[:10]}..{str(m['date'].max())[:10]}  vars={cov}")

    if unmapped:
        print("\n[!] Unmapped .dat station names (add to STATION_ALIASES):")
        for n in sorted(unmapped):
            print("    ", n)
    print(f"\nDone. {len(summary)} station master files in {out}/")


if __name__ == "__main__":
    main()
