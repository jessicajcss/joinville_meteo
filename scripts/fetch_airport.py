#!/usr/bin/env python3
"""
Update the airport station (SBJV, Joinville) from the Iowa Environmental Mesonet
ASOS archive and merge it into data/stations/aeroporto.csv.

Runs in GitHub Actions or locally (needs internet — NOT inside the Cowork sandbox).
It maps IEM 'data=all' (onlycomma) output to our standard station schema and
converts units:  °F->°C, knots->m/s, inches->mm, UTC->America/Sao_Paulo.

Reference: https://mesonet.agron.iastate.edu/request/download.phtml?network=BR__ASOS
"""
from __future__ import annotations
import io
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

STATION = "SBJV"
NETWORK = "BR__ASOS"
START = (2011, 1, 1)                     # pull full archive; merge is idempotent
TZ = "America/Sao_Paulo"
OUT = Path("datasets/hourly")            # airport series lives with the hourly datasets
KT_TO_MS = 0.514444
IN_TO_MM = 25.4


def fetch_csv() -> str:
    t = date.today()
    url = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"
           f"network={NETWORK}&station={STATION}&data=all&"
           f"year1={START[0]}&month1={START[1]}&day1={START[2]}&"
           f"year2={t.year}&month2={t.month}&day2={t.day}&"
           "tz=Etc/UTC&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&"
           "direct=no&report_type=3&report_type=4")
    print("[airport] GET", url)
    req = urllib.request.Request(url, headers={"User-Agent": "joinville-meteo/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode("utf-8", "replace")


def num(s: pd.Series) -> pd.Series:
    # 'T' (trace) -> tiny positive; 'M' already NaN via na_values
    return pd.to_numeric(s.replace({"T": "0.0001"}), errors="coerce")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(io.StringIO(fetch_csv()), na_values=["M"], low_memory=False)
    df.columns = [c.strip() for c in df.columns]

    out = pd.DataFrame()
    out["date"] = (pd.to_datetime(df["valid"], utc=True, errors="coerce")
                   .dt.tz_convert(TZ).dt.tz_localize(None))
    if "tmpf" in df:  out["temp"] = (num(df["tmpf"]) - 32) * 5 / 9
    if "dwpf" in df:  out["dewpoint"] = (num(df["dwpf"]) - 32) * 5 / 9
    if "relh" in df:  out["umid"] = num(df["relh"])
    if "drct" in df:  out["wd"] = num(df["drct"])
    if "sknt" in df:  out["ws"] = num(df["sknt"]) * KT_TO_MS
    if "gust" in df:  out["gust"] = num(df["gust"]) * KT_TO_MS
    if "p01i" in df:  out["prec"] = num(df["p01i"]) * IN_TO_MM
    if "mslp" in df:  out["pressure"] = num(df["mslp"])

    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")

    fp = OUT / "aeroporto.csv"
    if fp.exists():
        old = pd.read_csv(fp, parse_dates=["date"])
        both = pd.concat([old, out], ignore_index=True)
        both["_n"] = both.drop(columns=["date"]).notna().sum(axis=1)
        out = (both.sort_values(["date", "_n"], ascending=[True, False])
               .drop_duplicates("date", keep="first").drop(columns="_n"))
    out.to_csv(fp, index=False)
    try:
        out.to_parquet(OUT / "aeroporto.parquet", index=False)
    except Exception:
        pass
    print(f"[airport] {len(out):,} rows -> {fp}  ({out['date'].min()}..{out['date'].max()})")


if __name__ == "__main__":
    main()
