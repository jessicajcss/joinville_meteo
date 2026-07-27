#!/usr/bin/env python3
"""
masters.py — read per-station master series regardless of on-disk format.

The repo commits the station masters as CSV (data/hourly/<code>.csv,
data/daily/<code>.csv). A local working copy usually also has the faster Parquet
copies next to them. A fresh CI checkout has only the CSV. These helpers read
whichever exists — Parquet preferred (faster), CSV as fallback — so the build
scripts run identically on a laptop and on a clean GitHub Actions runner. The two
formats carry the same columns, so downstream code is unaffected.
"""
from __future__ import annotations
import glob
import os
from pathlib import Path
import pandas as pd


def _index(dirpath) -> dict:
    """code -> master file path, preferring Parquet, falling back to CSV."""
    d = Path(dirpath)
    idx: dict[str, str] = {}
    for f in sorted(glob.glob(str(d / "*.parquet"))):
        idx.setdefault(os.path.basename(f)[:-8], f)
    for f in sorted(glob.glob(str(d / "*.csv"))):
        idx.setdefault(os.path.basename(f)[:-4], f)   # only used if no parquet for that code
    return idx


def codes(dirpath) -> list:
    """Sorted station codes that have a master (parquet or csv) in dirpath."""
    return sorted(_index(dirpath).keys())


def read_file(path, parse_date: bool = True):
    """Read one master file (parquet or csv), parsing the date column."""
    df = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
    if parse_date and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def read(dirpath, code, parse_date: bool = True):
    """Read a station's master by code (parquet preferred, csv fallback). None if absent."""
    f = _index(dirpath).get(code)
    return None if f is None else read_file(f, parse_date)


def iter_masters(dirpath, parse_date: bool = True):
    """Yield (code, DataFrame) for every station master in dirpath, sorted by code."""
    for code, f in sorted(_index(dirpath).items()):
        yield code, read_file(f, parse_date)
