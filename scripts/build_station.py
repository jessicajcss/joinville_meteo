#!/usr/bin/env python3
"""
Self-contained per-station consolidator (designed to run ON the device, where the
raw archive lives, one station per call to stay within the shell time limit).

Merges the given source files (legacy *_raw.csv in m/s + TOA5 *_5.dat in km/h)
into one clean master, de-duplicating by timestamp and keeping the most complete
record. Writes <out>/<code>.csv (+ .parquet).

  python build_station.py --code ceasa --out data/stations  <file1> <file2> ...
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

FIELD_MAP = {
    "TIMESTAMP": "date", "Temp_Ar_Avg": "temp", "Umid_Rel": "umid", "R_Solar_Avg": "solar",
    "V_Vento_5": "ws", "V_Vento_Horaria": "ws", "D_Vento_5": "wd", "D_Vento_Horaria": "wd",
    "Rajada": "gust", "Dir_Rajada": "gust_dir", "Chuva_Tot": "prec", "PressATM": "pressure",
    "Orvalho": "dewpoint", "Ind_Calor": "heat_index", "WindChill": "wind_chill",
    "Nivel": "level", "Nivel_Max": "level_max", "Nivel_Min": "level_min",
}
NA = ["NAN", "-100", "-100.0", "-6999", "-6999.0", "-7999", "-99999", "-144.9"]
QC = {"temp": (-10, 50), "umid": (0, 100), "prec": (0, 500), "ws": (0, 100),
      "gust": (0, 120), "wd": (0, 360), "gust_dir": (0, 360), "solar": (0, 1600),
      "pressure": (800, 1050), "dewpoint": (-10, 40), "level": (-50, 5000)}
STD = ["date", "temp", "umid", "prec", "ws", "wd", "gust", "gust_dir", "solar",
       "pressure", "dewpoint", "heat_index", "wind_chill", "level", "level_max", "level_min"]
TZ = "America/Sao_Paulo"


def parse_toa5(path: Path) -> pd.DataFrame:
    names = pd.read_csv(path, skiprows=1, nrows=1, header=None, encoding="latin-1").iloc[0].tolist()
    df = pd.read_csv(path, skiprows=4, header=None, names=names, encoding="latin-1",
                     na_values=NA, low_memory=False)
    keep = {c: FIELD_MAP[c] for c in df.columns if c in FIELD_MAP}
    df = df[list(keep)].rename(columns=keep)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    for c in [c for c in df.columns if c != "date"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("ws", "gust"):                      # km/h -> m/s
        if c in df.columns:
            df[c] = df[c] / 3.6
    for c, (lo, hi) in QC.items():
        if c in df.columns:
            df.loc[(df[c] < lo) | (df[c] > hi), c] = np.nan
    return df


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = (pd.to_datetime(df["date"], utc=True, errors="coerce")
                  .dt.tz_convert(TZ).dt.tz_localize(None))
    return df.dropna(subset=["date"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--out", default="data/stations")
    ap.add_argument("sources", nargs="+")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    frames = []
    for s in a.sources:
        p = Path(s)
        if not p.exists():
            print(f"  skip (missing): {p.name}"); continue
        try:
            d = parse_toa5(p) if p.suffix.lower() == ".dat" else load_csv(p)
            frames.append(d)
            print(f"  + {p.name}: {len(d):,} rows")
        except Exception as e:
            print(f"  ! FAILED {p.name}: {e}")
    if not frames:
        print("no sources"); return

    df = pd.concat(frames, ignore_index=True)
    for c in STD:
        if c not in df.columns:
            df[c] = np.nan
    df = df[STD]
    df["date"] = pd.to_datetime(df["date"])
    df["_n"] = df.drop(columns=["date"]).notna().sum(axis=1)
    df = (df.sort_values(["date", "_n"], ascending=[True, False])
          .drop_duplicates("date", keep="first").drop(columns="_n").reset_index(drop=True))
    # drop all-empty columns for compactness
    keep = ["date"] + [c for c in STD if c != "date" and df[c].notna().any()]
    df = df[keep]
    df.to_csv(out / f"{a.code}.csv", index=False)
    try:
        df.to_parquet(out / f"{a.code}.parquet", index=False)
    except Exception:
        pass
    print(f"[{a.code}] {len(df):,} rows | {str(df['date'].min())[:10]}..{str(df['date'].max())[:10]} "
          f"| vars={[c for c in keep if c!='date']}")


if __name__ == "__main__":
    main()
