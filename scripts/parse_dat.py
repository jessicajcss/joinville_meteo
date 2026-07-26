#!/usr/bin/env python3
"""
Parser for Campbell Scientific TOA5 .dat files (Joinville stations).

TOA5 layout:
  line 1: "TOA5","<station>","<logger>",...,"<table>"
  line 2: field names   ("TIMESTAMP","RECORD","Temp_Ar_Avg",...)
  line 3: units         ("TS","RN","Deg C",...)
  line 4: aggregation   ("","","Avg",...)
  line 5+: data
Missing values are encoded as "NAN" or the sentinels -100 / -6999 / -144.9.
Wind speed/gust are in km/h in the loggers; we standardize to m/s.

Schemas vary by station type:
  - full met  : Temp_Ar_Avg, Umid_Rel, R_Solar_Avg, V_Vento_5, D_Vento_5, Rajada, Chuva_Tot, PressATM, ...
  - met+hydro : the above + Nivel* (river level)
  - hydro only: Chuva_Tot + Nivel* only (rain-gauge / river station, no temp/wind)
Mapping is by FIELD NAME, so any subset parses correctly.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

# Campbell field name -> standard column
FIELD_MAP = {
    "TIMESTAMP": "date",
    "Temp_Ar_Avg": "temp", "Umid_Rel": "umid", "R_Solar_Avg": "solar",
    "V_Vento_5": "ws", "D_Vento_5": "wd", "Rajada": "gust", "Dir_Rajada": "gust_dir",
    "Chuva_Tot": "prec", "PressATM": "pressure", "Orvalho": "dewpoint",
    "Ind_Calor": "heat_index", "WindChill": "wind_chill",
    "Nivel": "level", "Nivel_Max": "level_max", "Nivel_Min": "level_min",
}
KMH_TO_MS = 1.0 / 3.6                       # wind km/h -> m/s
NA_SENTINELS = ["NAN", "-100", "-100.0", "-6999", "-6999.0", "-7999", "-99999", "-144.9"]

# Physically plausible ranges (QC): value outside -> NaN
QC_RANGE = {
    "temp": (-10, 50), "umid": (0, 100), "prec": (0, 500), "ws": (0, 100),
    "gust": (0, 120), "wd": (0, 360), "gust_dir": (0, 360), "solar": (0, 1600),
    "pressure": (800, 1050), "dewpoint": (-10, 40), "level": (-50, 5000),
}


def station_name(path: Path) -> str:
    """Station name from TOA5 header line 1 (2nd quoted field)."""
    with open(path, "r", encoding="latin-1") as fh:
        first = fh.readline()
    parts = [p.strip().strip('"') for p in first.split('",')]
    return parts[1] if len(parts) > 1 else path.stem


def parse_toa5(path: Path) -> pd.DataFrame:
    """Parse a TOA5 .dat file into the standard wide schema (local-naive datetimes)."""
    path = Path(path)
    names = pd.read_csv(path, skiprows=1, nrows=1, header=None, encoding="latin-1").iloc[0].tolist()
    df = pd.read_csv(path, skiprows=4, header=None, names=names, encoding="latin-1",
                     na_values=NA_SENTINELS, low_memory=False)
    keep = {c: FIELD_MAP[c] for c in df.columns if c in FIELD_MAP}
    df = df[list(keep)].rename(columns=keep)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    for c in [c for c in df.columns if c != "date"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # wind km/h -> m/s
    for c in ("ws", "gust"):
        if c in df.columns:
            df[c] = df[c] * KMH_TO_MS
    # QC clamp
    for c, (lo, hi) in QC_RANGE.items():
        if c in df.columns:
            df.loc[(df[c] < lo) | (df[c] > hi), c] = np.nan
    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        d = parse_toa5(Path(p))
        print(f"{station_name(Path(p)):16s} {Path(p).name:20s} rows={len(d):>8,} "
              f"cols={[c for c in d.columns if c!='date']}")
        print("   range:", d['date'].min(), "->", d['date'].max())
