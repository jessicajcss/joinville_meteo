#!/usr/bin/env python3
"""
Build site/data/enso.json — El Niño / La Niña (ENSO) classification for the
Chuva & Rio "Análise diária" overlay.

Source: NOAA/CPC Oceanic Niño Index (ONI), the 3-month running mean of the SST
anomaly in the Niño-3.4 region.  https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

Classification (NOAA official event rule):
  El Niño = ONI >= +0.5 °C  |  La Niña = ONI <= -0.5 °C
  ...for at least 5 CONSECUTIVE overlapping 3-month seasons.
Intensity (by |ONI| magnitude, per the widely used convention):
  weak 0.5-0.9 · moderate 1.0-1.4 · strong 1.5-1.9 · very strong >= 2.0

Runs in GitHub Actions (has internet). LIVE-FIRST: fetches the current ONI table so
the classification stays up to date automatically as NOAA publishes new seasons; if
the fetch fails it falls back to the bundled snapshot below so a build never breaks.
`--offline` forces the bundled snapshot (used to generate the file without network,
e.g. inside the Cowork sandbox).

  python scripts/build_enso.py                 # live NOAA, fallback to snapshot
  python scripts/build_enso.py --offline        # snapshot only
  python scripts/build_enso.py site/data/enso.json
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
SEAS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
SEAS_IX = {s: i for i, s in enumerate(SEAS)}   # season -> center-month index (Jan..Dec)
MIN_YEAR = 2010                                # dashboard shows 2011+; keep 2010 for run continuity

# Bundled snapshot — NOAA/CPC ONI, center-month values (DJF..NDJ), through 2026 MAM.
# Only used if the live fetch fails; CI normally overwrites this with fresh data.
BUNDLED = {
    2010: [1.5, 1.2, 0.8, 0.4, -0.2, -0.7, -1.0, -1.3, -1.6, -1.6, -1.6, -1.5],
    2011: [-1.3, -1.0, -0.8, -0.6, -0.5, -0.4, -0.4, -0.6, -0.8, -1.0, -1.0, -0.9],
    2012: [-0.7, -0.6, -0.5, -0.4, -0.2, 0.1, 0.3, 0.4, 0.4, 0.3, 0.1, -0.1],
    2013: [-0.3, -0.3, -0.2, -0.2, -0.3, -0.3, -0.4, -0.3, -0.2, -0.1, -0.1, -0.2],
    2014: [-0.3, -0.3, -0.1, 0.2, 0.3, 0.2, 0.1, 0.1, 0.3, 0.5, 0.7, 0.8],
    2015: [0.7, 0.6, 0.7, 0.8, 1.0, 1.3, 1.6, 1.9, 2.2, 2.5, 2.6, 2.8],
    2016: [2.6, 2.3, 1.7, 1.0, 0.5, 0.0, -0.3, -0.5, -0.6, -0.6, -0.6, -0.5],
    2017: [-0.2, 0.0, 0.2, 0.3, 0.4, 0.4, 0.2, -0.1, -0.3, -0.6, -0.8, -0.9],
    2018: [-0.8, -0.7, -0.6, -0.4, -0.1, 0.1, 0.1, 0.3, 0.5, 0.8, 1.0, 0.9],
    2019: [0.9, 0.9, 0.8, 0.8, 0.6, 0.5, 0.3, 0.2, 0.2, 0.4, 0.6, 0.7],
    2020: [0.6, 0.6, 0.5, 0.3, 0.0, -0.2, -0.4, -0.5, -0.8, -1.1, -1.2, -1.1],
    2021: [-0.9, -0.8, -0.7, -0.5, -0.4, -0.3, -0.3, -0.4, -0.6, -0.8, -0.9, -0.9],
    2022: [-0.8, -0.8, -0.9, -1.0, -0.9, -0.8, -0.8, -0.9, -1.0, -0.9, -0.8, -0.7],
    2023: [-0.5, -0.3, 0.0, 0.3, 0.6, 0.8, 1.1, 1.4, 1.6, 1.8, 2.0, 2.1],
    2024: [1.9, 1.6, 1.3, 0.8, 0.5, 0.2, 0.1, -0.1, -0.2, -0.2, -0.3, -0.4],
    2025: [-0.4, -0.2, -0.1, 0.0, 0.0, 0.0, -0.1, -0.3, -0.4, -0.5, -0.6, -0.5],
    2026: [-0.4, -0.1, 0.1, 0.5],
}


def _pad12(v):
    v = list(v)
    return (v + [None] * 12)[:12]


def parse_ascii(txt: str) -> dict:
    """NOAA oni.ascii.txt: whitespace columns  SEAS  YR  TOTAL  ANOM."""
    out: dict = {}
    for line in txt.splitlines():
        p = line.split()
        if len(p) < 4 or p[0] not in SEAS_IX:
            continue                                  # skips the header row
        try:
            y, anom = int(p[1]), float(p[3])
        except ValueError:
            continue
        out.setdefault(y, [None] * 12)[SEAS_IX[p[0]]] = anom
    return out


def fetch_live() -> dict | None:
    try:
        req = urllib.request.Request(ONI_URL, headers={"User-Agent": "joinville-meteo/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode("utf-8", "replace")
        oni = parse_ascii(txt)
        # sanity: must contain a known anchor value (2015-16 super El Niño peak)
        if oni.get(2015) and oni[2015][SEAS_IX["NDJ"]] is not None and len(oni) > 30:
            return oni
        print("[enso] live table failed sanity check, ignoring", file=sys.stderr)
    except Exception as e:                                          # noqa: BLE001
        print(f"[enso] live fetch failed: {e}", file=sys.stderr)
    return None


def classify(oni: dict) -> dict:
    """Apply the 5-consecutive-season rule on the chronological center-month series."""
    years = sorted(oni)
    seq = [[y, m, _pad12(oni[y])[m]] for y in years for m in range(12)]
    n = len(seq)
    phase = [0] * n

    def mark(ok, val):
        i = 0
        while i < n:
            if seq[i][2] is not None and ok(seq[i][2]):
                j = i
                while j < n and seq[j][2] is not None and ok(seq[j][2]):
                    j += 1
                if j - i >= 5:
                    for k in range(i, j):
                        phase[k] = val
                i = j
            else:
                i += 1

    mark(lambda a: a >= 0.5, 1)
    mark(lambda a: a <= -0.5, -1)

    byyear: dict = {}
    for (y, m, a), p in zip(seq, phase):
        e = byyear.setdefault(y, {"oni": [None] * 12, "phase": [0] * 12})
        e["oni"][m] = a
        e["phase"][m] = p
    return byyear


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(ROOT / "site" / "data" / "enso.json"))
    ap.add_argument("--offline", action="store_true", help="use bundled snapshot, no network")
    a = ap.parse_args()

    oni = None if a.offline else fetch_live()
    source = "NOAA/CPC ONI (oni.ascii.txt, live)"
    if oni is None:
        oni = {y: list(v) for y, v in BUNDLED.items()}
        source = "NOAA/CPC ONI (bundled snapshot)"
        print("[enso] using bundled snapshot", file=sys.stderr)

    byyear = classify(oni)
    years = {y: byyear[y] for y in byyear if y >= MIN_YEAR}
    doc = {
        "source": source,
        "url": ONI_URL,
        "rule": "El Nino ONI>=+0.5 / La Nina ONI<=-0.5 for >=5 consecutive overlapping 3-month seasons (NOAA)",
        "intensity": "weak 0.5-0.9 | moderate 1.0-1.4 | strong 1.5-1.9 | very strong >=2.0 (by |ONI|)",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "years": {str(y): years[y] for y in sorted(years)},
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # concise console summary of the classified events
    names = {1: "El Nino", -1: "La Nina"}
    seq = [(y, m, years[y]["phase"][m]) for y in sorted(years) for m in range(12)]
    evs, i = [], 0
    while i < len(seq):
        if seq[i][2] != 0:
            j = i
            while j < len(seq) and seq[j][2] == seq[i][2]:
                j += 1
            evs.append(f"{names[seq[i][2]]} {SEAS[0] and ''}{seq[i][0]}-{seq[i][1]+1:02d}→{seq[j-1][0]}-{seq[j-1][1]+1:02d}")
            i = j
        else:
            i += 1
    print(f"[enso] wrote {out} · {min(years)}..{max(years)} · {source}")
    print("[enso] events: " + " | ".join(evs))


if __name__ == "__main__":
    main()
