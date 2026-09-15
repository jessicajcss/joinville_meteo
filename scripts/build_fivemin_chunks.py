#!/usr/bin/env python3
"""
build_fivemin_chunks.py — export the per-station 5-minute masters into the
year-chunked, gzipped files the dashboard's wind products actually read.

Reads : data/5min/<code>.csv      (fallback: data/5min/<code>.parquet)
Writes: site/data/stations/fivemin/<code>/<code>_<YYYY>.csv.gz

Why this exists
---------------
`update_datasets.py` grows the 5-minute masters under data/5min/ every time
new data arrives, but the dashboard never reads those masters directly. The
wind roses (Estação page), the mean-wind-speed / resultant-direction products
and the city wind heatmap (Cidade page) all read the committed *year-chunks*
under site/data/stations/fivemin/ via `fivemin.load_wind()`. Those chunks used
to be rebuilt by hand, so after a data update the temperature and rain plots
advanced while every wind product stayed frozen at the last hand-build. This
step re-exports the chunks from the masters on every run, keeping wind in
lockstep with temperature and rain.

Behaviour (safe / append-only)
------------------------------
* Only stations that have a master in data/5min/ are processed. Historical
  stations whose chunks were built once from the external archive have no
  master here and are left untouched.
* For each year present in the master, if the master extends beyond the
  existing chunk, the new rows are APPENDED to the chunk verbatim (the old
  bytes are preserved exactly; only rows newer than the chunk's last timestamp
  are added). A year whose chunk is already up to date is skipped, so closed
  past years are never rewritten and there is no commit churn.
* A brand-new year (no chunk yet) is written in full from the master.
* New rows are written with the chunk's existing column schema, so the
  "Baixar dados" 5-minute download is unchanged. Columns the master lacks
  (e.g. river level) are written empty, matching the existing rows.
* gzip is written with a fixed mtime so identical content yields identical
  bytes.
"""
from __future__ import annotations
import gzip
import io
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "5min"
OUT = ROOT / "site" / "data" / "stations" / "fivemin"

DATE_FMT = "%Y-%m-%d %H:%M:%S"


def load_master(code: str) -> pd.DataFrame | None:
    """Load a station's 5-minute master (CSV preferred, Parquet fallback)."""
    cs, pq = SRC / f"{code}.csv", SRC / f"{code}.parquet"
    d = None
    if cs.exists():
        try:
            d = pd.read_csv(cs)
        except Exception:
            d = None
    if d is None and pq.exists():
        try:
            d = pd.read_parquet(pq)
        except Exception:
            d = None
    if d is None or "date" not in d.columns:
        return None
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    return d if len(d) else None


def read_chunk_text(path: Path) -> str | None:
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read()


def chunk_header_and_last_date(text: str):
    """(header_columns[list], last_timestamp[Timestamp]) from a chunk's text."""
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    header = lines[0].split(",")
    last_date = pd.to_datetime(lines[-1].split(",")[0], errors="coerce")
    return header, last_date


def write_gz(path: Path, text: str) -> None:
    """Deterministic gzip (fixed mtime) so identical content == identical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = text.encode("utf-8")
    with open(path, "wb") as fout, gzip.GzipFile(
        fileobj=fout, mode="wb", compresslevel=6, mtime=0
    ) as gz:
        gz.write(raw)


def rows_to_csv(df: pd.DataFrame, columns: list[str], with_header: bool) -> str:
    """Serialise df to CSV text using exactly `columns` (missing -> empty)."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime(DATE_FMT)
    out = out.reindex(columns=columns)
    buf = io.StringIO()
    out.to_csv(buf, index=False, header=with_header)
    return buf.getvalue()


def main() -> None:
    if not SRC.is_dir():
        print("no data/5min/ masters — nothing to export")
        return
    codes = sorted({p.stem for p in SRC.glob("*.csv")} | {p.stem for p in SRC.glob("*.parquet")})
    written = 0
    for code in codes:
        m = load_master(code)
        if m is None:
            continue
        m = m.assign(_y=m["date"].dt.year)
        for yr, g in m.groupby("_y"):
            yr = int(yr)
            g = g.drop(columns="_y")
            path = OUT / code / f"{code}_{yr}.csv.gz"
            old_text = read_chunk_text(path)

            if old_text is None:
                # brand-new year: write the whole thing from the master
                text = rows_to_csv(g, list(g.columns), with_header=True)
                write_gz(path, text)
                written += 1
                print(f"  {code}_{yr}: new chunk, rows={len(g)} "
                      f"last={pd.to_datetime(g['date']).max()}")
                continue

            header, last_date = chunk_header_and_last_date(old_text)
            new_rows = g[g["date"] > last_date]
            if new_rows.empty:
                continue  # chunk already current — leave it untouched
            body = rows_to_csv(new_rows, header, with_header=False)
            if not old_text.endswith("\n"):
                old_text += "\n"
            write_gz(path, old_text + body)
            written += 1
            print(f"  {code}_{yr}: +{len(new_rows)} rows "
                  f"({last_date} -> {pd.to_datetime(new_rows['date']).max()})")
    print(f"fivemin chunks updated: {written}")


if __name__ == "__main__":
    main()
