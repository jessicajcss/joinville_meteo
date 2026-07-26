#!/usr/bin/env python3
"""
Build the whole HOURLY and DAILY datasets per station.

Sources (all native logger products — nothing invented):
  hourly : *_HR (year-sheet) spreadsheets  +  recent defesa_civil *_HR.dat
  daily  : *_DIARIA spreadsheets           +  recent defesa_civil *_DIARIA.dat
           (native extremes/totals: Tmax, Tmin, RHmax, RHmin, rain, radiation, gust)
Derived (documented, standard methods):
  daily means : temp_mean, umid_mean, ws_mean, pressure_mean, solar_mean
                = arithmetic mean of that day's HOURLY values; n_hours records how
                  many hours contributed (so partial days can be filtered).

Everything is de-duplicated by timestamp, native rows preferred, QC to physical
ranges, wind in m/s, local time.

Usage: python scripts/build_hourly_daily.py --xlsx <dir> --dat <dir> --out data
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from toa5 import parse_xlsx, parse_dat, MAP_INST, MAP_DAILY   # noqa: E402

# code -> (HR xlsx, DIARIA xlsx, recent HR .dat | None, recent DIARIA .dat | None)
STATIONS = {
    "ceasa":        ("CEASA_HR (2011-2026).xlsx",   "CEASA_DIARIA (2011-2026).xlsx",   "CEASA_HR.dat",    "CEASA_DIARIA.dat"),
    "flotflux":     ("FLOTFLUX_HR (2011-2026).xlsx","FLOTFLUX_DIARIA (2011-2026).xlsx","FLOTFLUX_HR.dat", "FLOTFLUX_DIARIA.dat"),
    "iateclube":    ("IATCLUB_HR (2011-2026).xlsx", "IATCLUB_DIARIA (2011-2026).xlsx", "IATCLUB_HR.dat",  "IATCLUB_DIARIA.dat"),
    "jardimparaiso":("J_PARAISO_HR (2011-2026).xlsx","J_PARAISO_DIARIA (2011-2026).xlsx","J_PARAISO_HR.dat","J_PARAISO_DIARIA.dat"),
    "divobras":     ("DIVOBRAS_HR (2011-2024).xlsx","DIVOBRAS_DIARIA (2011-2024).xlsx","DIVOBRAS_HR.dat", "DIVOBRAS_DIARIA.dat"),
    "aguasdejoi":   ("AGUAS_HR (2011-2024).xlsx",   "AGUAS_DIARIA (2011-2024).xlsx",   None, None),
    "cubatao":      ("CUBATAO_HR (2011-2024).xlsx", "CUBATAO_DIARIA (2011-2024).xlsx", None, None),
    "itaum":        ("ITAUM_HR (2011-2024).xlsx",   "ITAUM_DIARIA (2011-2024).xlsx",   None, None),
    "rodovia":      ("ESTR_SUL_HR (2011-2022).xlsx","ESTR_SUL_DIARIA (2011-2022).xlsx",None, None),
    "guanabara":    ("GUANABARA_HR (2011-2024).xlsx","GUANABARA_DIARIA (2011-2024).xlsx",None, None),
}


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    df["_n"] = df.drop(columns=["date"]).notna().sum(axis=1)
    df = (df.sort_values(["date", "_n"], ascending=[True, False])
          .drop_duplicates("date", keep="first").drop(columns="_n").reset_index(drop=True))
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, help="dir with *_HR/_DIARIA xlsx")
    ap.add_argument("--dat", required=True, help="dir with recent *_HR/_DIARIA .dat")
    ap.add_argument("--out", default="data")
    a = ap.parse_args()
    xdir, ddir = Path(a.xlsx), Path(a.dat)
    (Path(a.out) / "hourly").mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "daily").mkdir(parents=True, exist_ok=True)

    for code, (hrx, dix, hrd, did) in STATIONS.items():
        # ---- hourly ----
        h = parse_xlsx(xdir / hrx, MAP_INST)
        if hrd and (ddir / hrd).exists():
            h = pd.concat([h, parse_dat(ddir / hrd, MAP_INST)], ignore_index=True)
        h["date"] = pd.to_datetime(h["date"]).dt.floor("h")
        h = dedup(h)
        h = h[["date"] + [c for c in h.columns if c != "date" and h[c].notna().any()]]
        h.to_csv(Path(a.out) / "hourly" / f"{code}.csv", index=False)

        # ---- daily (native extremes/totals) ----
        d = parse_xlsx(xdir / dix, MAP_DAILY)
        if did and (ddir / did).exists():
            d = pd.concat([d, parse_dat(ddir / did, MAP_DAILY)], ignore_index=True)
        d["date"] = pd.to_datetime(d["date"]).dt.floor("D")
        d = dedup(d)

        # ---- daily means derived from hourly (documented) ----
        hh = h.copy(); hh["date"] = hh["date"].dt.floor("D")
        agg = {}
        for src, dst in [("temp", "temp_mean"), ("umid", "umid_mean"), ("ws", "ws_mean"),
                         ("pressure", "pressure_mean"), ("solar", "solar_mean")]:
            if src in hh.columns:
                agg[dst] = (src, "mean")
        means = hh.groupby("date").agg(n_hours=("date", "size"), **agg).reset_index()
        d = d.merge(means, on="date", how="outer").sort_values("date").reset_index(drop=True)
        d = d[["date"] + [c for c in d.columns if c != "date" and d[c].notna().any()]]
        d.to_csv(Path(a.out) / "daily" / f"{code}.csv", index=False)

        print(f"{code:13s} hourly {len(h):>7,} ({str(h['date'].min())[:10]}..{str(h['date'].max())[:10]}) | "
              f"daily {len(d):>5,} ({str(d['date'].min())[:10]}..{str(d['date'].max())[:10]})")

    # ---- rain QC: flag inch-code / non-physical / catch-up dumps across all masters ----
    from rain_qc import clean_dir
    qc = clean_dir(Path(a.out))
    print(f"[rain_qc] flagged {int(qc['n_flagged'].sum()) if len(qc) else 0} rain points "
          f"-> {Path(a.out) / 'processed' / 'rain_qc_flags.csv'}")


if __name__ == "__main__":
    main()
