#!/usr/bin/env python3
"""
build_udesc.py — ingest the UDESC/CCT weather station (Ecowitt-format 1-min CSV)
and produce hourly + daily masters matching the existing station schema.

Source: meteo/UDESC_meteo/*.CSV  (monthly files, 1-minute logging)
Station: UDESC — Centro de Ciências Tecnológicas (CCT), Joinville
Coords : -26.255151829918283, -48.855263545204416

Column mapping (Ecowitt -> master schema):
  Outdoor Temperature(C) -> temp      Outdoor Humidity(%) -> umid
  Wind(m/s)              -> ws        Wind Direction(deg) -> wd
  Gust(m/s)             -> gust      Solar Rad(w/m2)     -> solar
  Dew Point(C)          -> dewpoint  Heat Index(C)       -> heat_index
  Wind Chill(C)         -> wind_chill  (Daily Rain increments) -> prec

Rain: hourly precipitation is the sum of POSITIVE increments of the within-day
cumulative "Daily Rain(mm)" counter over each clock hour (midnight resets -> 0),
the standard reconstruction for a tipping-bucket accumulator. Daily total = the
day's maximum "Daily Rain(mm)".

QC: '-' and the no-sensor sentinel 6553/6553.5 -> NaN; implausible outdoor
temperatures (< -10 or > 45 C) -> NaN.

Importable API (used by the weekly updater update_datasets.py):
  is_ecowitt(path) -> bool
  process_paths([paths]) -> (hourly_df, daily_df)
"""
from __future__ import annotations
import glob, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC  = Path("/mnt/user-data/uploads/projeto_resposta_eventos/meteo/UDESC_meteo")
HOUT = ROOT / "data" / "hourly"
DOUT = ROOT / "data" / "daily"

UDESC_CODE = "udesc"
ECOWITT_MARKER = "Outdoor Temperature"     # header signature that identifies these files

COLS = {
    "Outdoor Temperature(C)": "temp",
    "Outdoor Humidity(%)":    "umid",
    "Wind(m/s)":              "ws",
    "Gust(m/s)":              "gust",
    "Wind Direction(deg)":    "wd",
    "Solar Rad(w/m2)":        "solar",
    "Dew Point(C)":           "dewpoint",
    "Heat Index(C)":          "heat_index",
    "Wind Chill(C)":          "wind_chill",
    "Daily Rain(mm)":         "daily_rain",
}


def is_ecowitt(path) -> bool:
    """True if the CSV header looks like an Ecowitt/UDESC console export."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            head = fh.readline()
        return ECOWITT_MARKER in head and "Time" in head
    except Exception:
        return False


def _read_one(f) -> pd.DataFrame:
    d = pd.read_csv(f, na_values=["-", "--", ""], low_memory=False, on_bad_lines="skip")
    d.columns = [c.strip() for c in d.columns]
    keep = {k: v for k, v in COLS.items() if k in d.columns}
    sub = d[["Time"] + list(keep)].rename(columns=keep)
    sub["date"] = pd.to_datetime(sub["Time"], format="%Y/%m/%d %H:%M:%S", errors="coerce")
    return sub.drop(columns=["Time"]).dropna(subset=["date"])


def clean(df: pd.DataFrame) -> pd.DataFrame:
    for c in ["temp", "umid", "ws", "gust", "wd", "solar", "dewpoint", "heat_index", "wind_chill", "daily_rain"]:
        if c in df: df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["solar", "dewpoint", "heat_index", "wind_chill"]:
        if c in df: df.loc[df[c].round() == 6553, c] = np.nan
    df.loc[(df["temp"] < -10) | (df["temp"] > 45), "temp"] = np.nan
    df.loc[(df["umid"] < 0) | (df["umid"] > 100), "umid"] = np.nan
    df.loc[(df["ws"] < 0) | (df["ws"] > 75), "ws"] = np.nan
    df.loc[(df["gust"] < 0) | (df["gust"] > 90), "gust"] = np.nan
    df.loc[(df["wd"] < 0) | (df["wd"] > 360), "wd"] = np.nan
    df.loc[df["solar"] < 0, "solar"] = np.nan
    return df


def _hourly_precip(daily_rain: pd.Series) -> pd.Series:
    day = daily_rain.index.normalize()
    inc = daily_rain.groupby(day).diff().clip(lower=0).fillna(0)
    return inc


def to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    inc = _hourly_precip(df["daily_rain"]) if "daily_rain" in df else pd.Series(0.0, index=df.index)
    df = df.assign(_pinc=inc)
    rad = np.radians(df["wd"])
    u = -df["ws"] * np.sin(rad); v = -df["ws"] * np.cos(rad)
    g = df.resample("h")
    out = pd.DataFrame({
        "temp": g["temp"].mean(), "umid": g["umid"].mean(), "solar": g["solar"].mean(),
        "ws": g["ws"].mean(), "gust": g["gust"].max(),
        "prec": df["_pinc"].resample("h").sum(min_count=1),
        "dewpoint": g["dewpoint"].mean(), "heat_index": g["heat_index"].mean(),
        "wind_chill": g["wind_chill"].mean(),
    })
    um = u.resample("h").mean(); vm = v.resample("h").mean()
    out["wd"] = (np.degrees(np.arctan2(-um, -vm)) % 360)
    out["gust_dir"] = np.nan
    out = out.dropna(how="all", subset=["temp", "umid", "ws", "prec", "solar"])
    return out.reset_index()[["date", "temp", "umid", "solar", "ws", "wd", "gust",
                              "gust_dir", "prec", "dewpoint", "heat_index", "wind_chill"]]


def to_daily(df: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    day = df.index.normalize()
    dr = df.groupby(day)["daily_rain"].max()
    hh = hourly.set_index("date"); g = hh.groupby(hh.index.normalize())
    out = pd.DataFrame({
        "temp_max": df.groupby(day)["temp"].max(), "temp_min": df.groupby(day)["temp"].min(),
        "umid_max": df.groupby(day)["umid"].max(), "umid_min": df.groupby(day)["umid"].min(),
        "solar_total": g["solar"].sum(min_count=1), "gust_max": df.groupby(day)["gust"].max(),
        "prec": dr, "dewpoint": df.groupby(day)["dewpoint"].mean(),
        "heat_index": df.groupby(day)["heat_index"].max(), "wind_chill": df.groupby(day)["wind_chill"].min(),
        "n_hours": g.size(), "temp_mean": g["temp"].mean(), "umid_mean": g["umid"].mean(),
        "ws_mean": g["ws"].mean(), "solar_mean": g["solar"].mean(),
    })
    out.index.name = "date"; out = out.reset_index()
    out["gust_dir"] = np.nan; out["level_max"] = np.nan; out["level_min"] = np.nan
    return out


def process_paths(paths):
    """Read + clean + resample a list of Ecowitt CSVs -> (hourly_df, daily_df)."""
    frames = [_read_one(f) for f in paths]
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last").set_index("date")
    df = clean(df)
    hourly = to_hourly(df)
    daily = to_daily(df, hourly)
    return hourly, daily


def main():
    print("reading UDESC_meteo/*.CSV ...")
    paths = sorted(glob.glob(str(SRC / "*.CSV")))
    for f in paths:
        print(f"  {os.path.basename(f)}")
    hourly, daily = process_paths(paths)
    HOUT.mkdir(parents=True, exist_ok=True); DOUT.mkdir(parents=True, exist_ok=True)
    for name, d, out in [("hourly", hourly, HOUT), ("daily", daily, DOUT)]:
        d.to_parquet(out / "udesc.parquet", index=False)
        d.to_csv(out / "udesc.csv", index=False)
        print(f"{name}: {len(d)} rows -> {out}/udesc.parquet")
    ht = hourly.dropna(subset=["temp"])
    print(f"hourly temp coverage: {ht['date'].min()} -> {ht['date'].max()} ({len(ht)} h)")
    print(f"total precip: {daily['prec'].sum():.1f} mm")


if __name__ == "__main__":
    main()
