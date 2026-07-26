#!/usr/bin/env python3
"""
TOA5 readers for the Joinville meteo archive — used by the consolidation
pipeline and the notebook. Two entry points:

  parse_dat(path)            -> tidy DataFrame from a Campbell .dat (TOA5) file
  parse_xlsx(path)           -> tidy DataFrame from a *_HR/_DIARIA (year-sheet) xlsx

Both map Campbell field names to a standard schema, convert wind km/h -> m/s,
strip the -100 / NAN / -6999 sentinels, and QC to physical ranges. The caller
passes which field map to use (5-min/hourly vs daily), so the same reader serves
every table type. Returns local-naive datetimes (America/Sao_Paulo already implied
by the loggers, which record local standard time).

NO values are invented here — every column comes from a real logger field.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

# 5-minute AND hourly instantaneous/averaged tables share these field names
MAP_INST = {
    "TIMESTAMP": "date",
    "Temp_Ar_Avg": "temp", "Umid_Rel": "umid", "R_Solar_Avg": "solar",
    "V_Vento_5": "ws", "V_Vento_Horaria": "ws",
    "D_Vento_5": "wd", "D_Vento_Horaria": "wd",
    "Rajada": "gust", "Dir_Rajada": "gust_dir", "Chuva_Tot": "prec",
    "PressATM": "pressure", "Orvalho": "dewpoint", "Ind_Calor": "heat_index",
    "WindChill": "wind_chill", "Nivel": "level", "Nivel_Max": "level_max",
    "Nivel_Min": "level_min",
}
# daily (DIARIA) tables store extremes + totals (no daily means)
MAP_DAILY = {
    "TIMESTAMP": "date",
    "Temp_Ar_Max": "temp_max", "Temp_Ar_Min": "temp_min",
    "Umid_Rel_Max": "umid_max", "Umid_Rel_Min": "umid_min",
    "Rad_Total_Tot": "solar_total", "Rajada": "gust_max", "Dir_Rajada": "gust_dir",
    "Chuva_Tot": "prec", "Nivel_Max": "level_max", "Nivel_Min": "level_min",
    "Orvalho": "dewpoint", "Ind_Calor": "heat_index", "WindChill": "wind_chill",
}
NA_SENTINELS = ["NAN", "-100", "-100.0", "-6999", "-6999.0", "-7999", "-99999", "-144.9"]
WIND_COLS = {"ws", "gust", "gust_max"}          # km/h -> m/s
QC = {"temp": (-10, 50), "temp_max": (-10, 50), "temp_min": (-10, 50),
      "umid": (0, 100), "umid_max": (0, 100), "umid_min": (0, 100),
      "prec": (0, 500), "ws": (0, 100), "gust": (0, 120), "gust_max": (0, 120),
      "wd": (0, 360), "gust_dir": (0, 360), "solar": (0, 1600),
      "solar_total": (0, 45000), "pressure": (800, 1050), "dewpoint": (-10, 40),
      "level": (-50, 5000), "level_max": (-50, 5000), "level_min": (-50, 5000)}
MIN_DATE = pd.Timestamp("2010-01-01")           # clip stray pre-network timestamps


def station_name(path) -> str:
    """Station name from the TOA5 header line 1 (2nd quoted field)."""
    with open(path, "r", encoding="latin-1") as fh:
        first = fh.readline()
    parts = [p.strip().strip('"') for p in first.split('",')]
    return parts[1].strip('"') if len(parts) > 1 else Path(path).stem


def _finalize(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    keep = {c: mapping[c] for c in df.columns if c in mapping}
    df = df[list(keep)].rename(columns=keep)
    # collapse any duplicate target columns (malformed headers) keeping first non-null
    df = df.loc[:, ~df.columns.duplicated()]
    d = df["date"]
    if not pd.api.types.is_datetime64_any_dtype(d):
        parsed = pd.to_datetime(d, format="%Y-%m-%d %H:%M:%S", errors="coerce")  # fast path
        miss = parsed.isna() & d.notna()
        if miss.any():
            parsed.loc[miss] = pd.to_datetime(d[miss], errors="coerce")
        d = parsed
    df = df.assign(date=d)
    df = df.dropna(subset=["date"])
    df = df[df["date"] >= MIN_DATE]
    for c in [c for c in df.columns if c != "date"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in WIND_COLS & set(df.columns):
        df[c] = df[c] / 3.6
    for c, (lo, hi) in QC.items():
        if c in df.columns:
            df.loc[(df[c] < lo) | (df[c] > hi), c] = np.nan
    return df.sort_values("date").reset_index(drop=True)


def parse_dat(path, mapping: dict = MAP_INST) -> pd.DataFrame:
    path = Path(path)
    names = pd.read_csv(path, skiprows=1, nrows=1, header=None, encoding="latin-1").iloc[0].tolist()
    df = pd.read_csv(path, skiprows=4, header=None, names=names, encoding="latin-1",
                     na_values=NA_SENTINELS, low_memory=False)
    return _finalize(df, mapping)


def parse_xlsx(path, mapping: dict = MAP_INST) -> pd.DataFrame:
    """Year-sheet spreadsheets: each sheet is a TOA5 dump with 2 extra leading
    columns (Data, Hora). Auto-detect the field-name row (contains 'TIMESTAMP')."""
    path = Path(path)
    try:
        xl = pd.ExcelFile(path, engine="calamine")   # ~50x faster than openpyxl
        engine = "calamine"
    except Exception:
        xl = pd.ExcelFile(path); engine = None
    frames = []
    for sh in xl.sheet_names:
        raw = pd.read_excel(path, sheet_name=sh, header=None, engine=engine)
        hdr = None
        for i in range(min(8, len(raw))):
            if (raw.iloc[i].astype(str).str.strip() == "TIMESTAMP").any():
                hdr = i
                break
        if hdr is None:
            continue
        names = raw.iloc[hdr].tolist()
        block = raw.iloc[hdr + 1:].copy()
        block.columns = names
        block = block.loc[:, ~block.columns.duplicated()]   # drop duplicate-named cols
        block = block.replace(NA_SENTINELS, np.nan)
        frames.append(block)
    if not frames:
        return pd.DataFrame(columns=list(mapping.values()))
    return _finalize(pd.concat(frames, ignore_index=True), mapping)
