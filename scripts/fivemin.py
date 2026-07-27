#!/usr/bin/env python3
"""
fivemin.py — shared loader for the per-station 5-minute masters.

The 5-minute records are the FINEST resolution committed to the repo. To stay
within GitHub's per-file limit they are stored year-chunked and gzip-compressed:

    site/data/stations/fivemin/<code>/<code>_<YYYY>.csv.gz

Each chunk is a plain CSV (same columns as the hourly master: date, wd, ws, ...).
The dashboard's wind products — the wind roses, the predominant (resultant)
direction and the mean-wind-speed climatology — read these 5-minute records so
that the direction statistics use every ~5-minute sample rather than one value
per hour. If the 5-minute store is absent for a station, callers fall back to the
hourly master, so the pipeline still runs on a checkout without the archive.

Reading is cheap: only the (date, wd, ws) columns are parsed, so a full station
(~1.3 M rows) loads in ~1-2 s.
"""
from __future__ import annotations
import glob
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FIVEMIN = ROOT / "site" / "data" / "stations" / "fivemin"

_WIND_COLS = ("date", "wd", "ws")


def codes() -> list[str]:
    """Station codes that have a 5-minute chunk directory."""
    if not FIVEMIN.is_dir():
        return []
    return sorted(p.name for p in FIVEMIN.iterdir()
                  if p.is_dir() and any(p.glob("*.csv.gz")))


def has_5min(code: str) -> bool:
    return bool(glob.glob(str(FIVEMIN / code / f"{code}_*.csv.gz")))


def _year_of(path: str) -> int:
    try:
        return int(path.rsplit("_", 1)[1][:4])
    except Exception:
        return -1


def load_wind(code: str, years=None):
    """Return a DataFrame(date[datetime], wd[float], ws[float]) at 5-min
    resolution for one station, concatenated across year chunks and sorted by
    time. Returns None if the station has no 5-minute store or no wind columns.
    Rows with an unparseable date are dropped; wd/ws are left as-is (QC — calm,
    stuck-vane and the exact-0 sentinel — is applied by the caller, identically
    to the hourly path). If `years` is given (an iterable of ints), only those
    year chunks are read — used by the near-real-time build to load just the
    recent window instead of the full multi-year archive."""
    files = sorted(glob.glob(str(FIVEMIN / code / f"{code}_*.csv.gz")))
    if years is not None:
        yrs = {int(y) for y in years}
        files = [f for f in files if _year_of(f) in yrs]
    if not files:
        return None
    frames = []
    for f in files:
        try:
            x = pd.read_csv(f, usecols=lambda c: c in _WIND_COLS)
        except Exception:
            continue
        if "wd" in x.columns and "ws" in x.columns:
            frames.append(x)
    if not frames:
        return None
    d = pd.concat(frames, ignore_index=True)
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return d if len(d) else None
