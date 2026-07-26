#!/usr/bin/env python3
"""
Data-availability (coverage) plots for the consolidated station datasets.

For each temporal resolution it renders a station x month heatmap of monthly
completeness = observations_present / observations_expected, so gaps and their
fills are visible at a glance. Reusable from the pipeline and the notebook.

  python scripts/plot_coverage.py --datasets datasets --out figs
  # or import: from plot_coverage import coverage_table, coverage_heatmap

Expected observations per day by resolution: 5min -> 288, hourly -> 24,
daily -> 1 (10-min gauges -> 144).
"""
from __future__ import annotations
import argparse
import glob
import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

PER_DAY = {"5min": 288, "hourly": 24, "daily": 1, "gauges": 144}
# dataviz sequential-blue ramp (light -> dark = low -> high completeness)
_BLUES = ["#eaf2fc", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
CMAP = LinearSegmentedColormap.from_list("blues", _BLUES)
CMAP.set_bad("#efeeea")                      # months with no data -> light grey

# display names + a sensible top-to-bottom order (met/hidromet first, hydro last)
NAMES = {"ceasa": "Ceasa", "iateclube": "Iate Clube", "flotflux": "Cachoeira (Flotflux)",
         "cubatao": "Cubatão", "itaum": "Itaum", "aguasdejoi": "Águas (Bucarein)",
         "rodovia": "Rodovia do Arroz", "guanabara": "Guanabara",
         "jardimparaiso": "Paraíso", "divobras": "Unidade de Obras"}
ORDER = ["ceasa", "iateclube", "flotflux", "cubatao", "itaum", "aguasdejoi",
         "rodovia", "guanabara", "jardimparaiso", "divobras"]
MIN_DATE = pd.Timestamp("2010-01-01")        # ignore stray pre-network timestamps


def coverage_table(data_dir: str, per_day: int) -> pd.DataFrame:
    """Long table (station, month-period, n_obs, pct) for a folder of <code>.csv."""
    rows = []
    for f in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        code = os.path.basename(f)[:-4]
        d = pd.read_csv(f, usecols=["date"])
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["date"])
        d = d[d["date"] >= MIN_DATE]
        m = d.groupby(d["date"].dt.to_period("M")).size()
        for p, n in m.items():
            rows.append((code, p, int(n)))
    c = pd.DataFrame(rows, columns=["station", "mp", "n"])
    c["days"] = c["mp"].dt.days_in_month
    c["pct"] = (100 * c["n"] / (c["days"] * per_day)).clip(0, 100)
    return c


def coverage_heatmap(cov: pd.DataFrame, title: str, out_png: str,
                     start="2011-01", end="2026-07") -> None:
    full = pd.period_range(start, end, freq="M")
    present = [c for c in ORDER if c in set(cov["station"])] + \
              [c for c in sorted(cov["station"].unique()) if c not in ORDER]
    piv = cov.pivot_table(index="station", columns="mp", values="pct").reindex(
        index=present, columns=full)
    fig, ax = plt.subplots(figsize=(15, 0.5 * len(present) + 1.2))
    im = ax.imshow(np.ma.masked_invalid(piv.values), aspect="auto", cmap=CMAP,
                   vmin=0, vmax=100, interpolation="nearest")
    ax.set_yticks(range(len(present)))
    ax.set_yticklabels([NAMES.get(c, c) for c in present], fontsize=11)
    yrs = [i for i, p in enumerate(full) if p.month == 1]
    ax.set_xticks(yrs); ax.set_xticklabels([full[i].year for i in yrs], fontsize=10)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-.5, len(full), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(present), 1), minor=True)
    ax.grid(which="minor", color="white", lw=.6)
    ax.tick_params(which="both", length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cb.set_label("Cobertura mensal (%)", fontsize=10); cb.outline.set_visible(False)
    ax.set_title(title, fontsize=14, fontweight="600", pad=12, loc="left")
    plt.tight_layout()
    plt.savefig(out_png, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="datasets", help="dir with 5min/ hourly/ daily/")
    ap.add_argument("--out", default="figs")
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    titles = {"5min": "séries de 5 minutos", "hourly": "séries horárias", "daily": "séries diárias"}
    for tier, label in titles.items():
        d = os.path.join(a.datasets, tier)
        if not os.path.isdir(d):
            continue
        cov = coverage_table(d, PER_DAY[tier])
        coverage_heatmap(cov, f"Joinville — cobertura das {label} por estação",
                         os.path.join(a.out, f"coverage_{tier}.png"))
        print(f"[{tier}] {cov['station'].nunique()} stations -> {a.out}/coverage_{tier}.png")


if __name__ == "__main__":
    main()
