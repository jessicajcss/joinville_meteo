#!/usr/bin/env python3
"""
build_tupann_nowcast.py  —  TUPANN satellite-nowcast → three-scale dashboard products.

Turns ONE TUPANN 2 km rain-rate nowcast field (the deployable tier-B / U-Net field, or the
raw TUPANN field) into the Joinville dashboard's Nowcast layer at THREE scales:

  (a) best-resolution grid  (2 km cells within the municipality)     -> tupann_grid.geojson
  (b) hydrographic basin    (site/data/bacias.geojson)               -> tupann_basins.{geojson,csv}
  (c) municipal district    (site/data/bairros.geojson)              -> tupann_bairros.{geojson,csv}

plus a calibrated warning list (tupann_warnings.json) and run metadata (tupann_meta.json).

This is the CPU-only, GitHub-Actions-ready half of the real-time loop (notebook 10). It does NOT
run TUPANN — the model field is produced upstream (external GPU or ONNX-CPU) and dropped as an
.npz in site/data/tupann/incoming/. Everything here is numpy + geopandas: seconds on a CPU runner.

Design mirrors scripts/build_wrf_basins.py (same equal-area projection, same three scales, same
"uniform field -> identical value everywhere" invariant) but is fully INDEPENDENT: separate script,
separate tupann_* outputs, separate tupann/ subfolder. It reads the existing bacias/bairros/limite
GeoJSONs read-only and writes only new tupann_* files.

WARNINGS are the calibrated operating point (nb 05e / 07b §14): a decision threshold tau per tier
applied to the nowcast field — NOT the raw OMM intensity class — because TUPANN under-warns at the
heavy tail and the calibration is what recovers recall. tau_heavy / tau_mod travel in the incoming
.npz meta (so the model-specific calibrated thresholds flow through); documented defaults below.

Std-lib + numpy + pandas + geopandas + shapely + pyproj only.  MIT-style, no network.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, box as shp_box, shape as shp_shape

# ---- defaults (overridable via the incoming .npz meta) -----------------------------------------
EQ_AREA   = "EPSG:31982"      # UTM 22S — metric, for area-weighting / % coverage (same as WRF builder)
WGS84     = "EPSG:4326"
TAU_HEAVY_DEFAULT = 4.0       # calibrated heavy tier (07b §14 max-CSI, ≥8 mm/h event) — REFIT PER MODEL
TAU_MOD_DEFAULT   = 1.4       # calibrated moderate tier (07b §14 max-CSI, ≥4 mm/h event)
MARGIN_DEG = 0.03             # keep grid cells just outside the municipal boundary too
LEVELS = ["VERDE", "AMARELO", "LARANJA", "VERMELHO"]   # none / watch-moderate / moderate / heavy


def _p90(a):
    a = np.asarray(a, float); a = a[np.isfinite(a)]
    return float(np.percentile(a, 90)) if a.size else np.nan


def classify(value, tau_mod, tau_heavy):
    """Warning level from the calibrated operating point on the nowcast rain-rate (mm/h)."""
    if not np.isfinite(value):
        return "VERDE"
    if value >= tau_heavy:  return "VERMELHO"     # heavy (predicts ≥8 mm/h event)
    if value >= tau_mod:    return "LARANJA"      # moderate (predicts ≥4 mm/h event)
    if value >= tau_mod * 0.5: return "AMARELO"   # watch (approaching the moderate threshold)
    return "VERDE"


def load_field(npz_path: Path):
    """Load a TUPANN nowcast field artifact. Expects field2d + lat2d + lon2d (+ optional meta_json)."""
    z = np.load(npz_path, allow_pickle=True)
    field = np.asarray(z["field2d"], float)
    lat2d = np.asarray(z["lat2d"], float)
    lon2d = np.asarray(z["lon2d"], float)
    meta = {}
    if "meta_json" in z:
        try: meta = json.loads(str(z["meta_json"]))
        except Exception: meta = {}
    assert field.shape == lat2d.shape == lon2d.shape, "field2d / lat2d / lon2d must share shape"
    return field, lat2d, lon2d, meta


def zonal(points_gdf, zones_path, name_field, tau_mod, tau_heavy):
    """Aggregate the 2 km cell points onto polygon zones; return a GeoDataFrame with stats + level."""
    z = gpd.read_file(zones_path).to_crs(WGS84)
    z["_zid"] = np.arange(len(z))
    z_m = z.to_crs(EQ_AREA); z["_area_km2"] = z_m.area / 1e6
    j = gpd.sjoin(points_gdf, z[["_zid", "geometry"]], predicate="within", how="inner")
    rows = []
    for zid, grp in j.groupby("_zid"):
        v = grp["rain"].to_numpy(float)
        mean, mx, p90 = float(np.nanmean(v)), float(np.nanmax(v)), _p90(v)
        rows.append(dict(_zid=int(zid), n_cells=int(len(v)),
                         mean_mm_h=round(mean, 2), max_mm_h=round(mx, 2), p90_mm_h=round(p90, 2),
                         area_ge_mod_pct=round(100 * float(np.mean(v >= tau_mod)), 1),
                         area_ge_heavy_pct=round(100 * float(np.mean(v >= tau_heavy)), 1),
                         level=classify(p90, tau_mod, tau_heavy)))   # zone level driven by its p90 (worst-decile)
    stats = pd.DataFrame(rows)
    out = z.merge(stats, on="_zid", how="left")
    out["name"] = out[name_field].astype(str)
    for c in ["n_cells", "mean_mm_h", "max_mm_h", "p90_mm_h", "area_ge_mod_pct", "area_ge_heavy_pct"]:
        out[c] = out[c].fillna(0.0)
    out["level"] = out["level"].fillna("VERDE")
    return out


def main():
    ap = argparse.ArgumentParser(description="Build the TUPANN nowcast three-scale dashboard products.")
    ap.add_argument("--field", required=True, help="incoming .npz (field2d/lat2d/lon2d + meta)")
    ap.add_argument("--data", default="site/data", help="dashboard data dir (has bacias/bairros/limite geojson)")
    ap.add_argument("--out", default="site/data/tupann", help="output dir (independent tupann/ subfolder)")
    args = ap.parse_args()

    data = Path(args.data); out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    field, lat2d, lon2d, meta = load_field(Path(args.field))

    tau_heavy = float(meta.get("tau_heavy", TAU_HEAVY_DEFAULT))
    tau_mod   = float(meta.get("tau_mod",   TAU_MOD_DEFAULT))
    issue_utc = meta.get("issue_utc", "unknown")
    lead_min  = int(meta.get("lead_min", 0))
    model     = meta.get("model", "TUPANN")

    # municipal boundary (+margin) as the grid clip
    lim = gpd.read_file(data / "limite.geojson").to_crs(WGS84)
    minx, miny, maxx, maxy = lim.total_bounds
    clip = shp_box(minx - MARGIN_DEG, miny - MARGIN_DEG, maxx + MARGIN_DEG, maxy + MARGIN_DEG)

    # 2 km cell-centre points inside the clip box
    la = lat2d.ravel(); lo = lon2d.ravel(); rr = np.clip(field.ravel(), 0, None)
    inbox = (lo >= minx - MARGIN_DEG) & (lo <= maxx + MARGIN_DEG) & (la >= miny - MARGIN_DEG) & (la <= maxy + MARGIN_DEG)
    la, lo, rr = la[inbox], lo[inbox], rr[inbox]
    pts = gpd.GeoDataFrame({"rain": rr}, geometry=[Point(x, y) for x, y in zip(lo, la)], crs=WGS84)
    # keep only points within the municipality (+margin) for the grid product
    keep = pts.within(clip)
    pts = pts[keep].reset_index(drop=True)

    # (a) GRID — cell points with rain + level. Thin to a cap so the web layer stays light no
    # matter the input resolution (the native 2 km grid is ~hundreds of in-municipality cells;
    # a finer field is strided down — noted in meta as grid_thinned).
    GRID_CAP = 4000
    grid_pts = pts
    stride = 1
    if len(pts) > GRID_CAP:
        stride = int(np.ceil(len(pts) / GRID_CAP))
        grid_pts = pts.iloc[::stride].reset_index(drop=True)
    grid_feats = []
    for _, r in grid_pts.iterrows():
        lvl = classify(float(r["rain"]), tau_mod, tau_heavy)
        grid_feats.append(dict(type="Feature",
            geometry=dict(type="Point", coordinates=[round(r.geometry.x, 5), round(r.geometry.y, 5)]),
            properties=dict(rain_mm_h=round(float(r["rain"]), 2), level=lvl)))
    grid_gj = dict(type="FeatureCollection",
                   properties=dict(scale="grid_2km", issue_utc=issue_utc, lead_min=lead_min, model=model),
                   features=grid_feats)
    (out / "tupann_grid.geojson").write_text(json.dumps(grid_gj), encoding="utf-8")

    # (b) BASINS  &  (c) BAIRROS
    basins = zonal(pts, data / "bacias.geojson",  "Nomes",      tau_mod, tau_heavy)
    bairros = zonal(pts, data / "bairros.geojson", "Nome_Bairr", tau_mod, tau_heavy)

    def dump(gdf, stem, keepcols):
        g = gdf.copy()
        g["area_km2"] = g["_area_km2"].round(2)
        gj = g[keepcols + ["area_km2", "geometry"]]         # clean props (drop _zid / raw source cols)
        gj.to_file(out / f"{stem}.geojson", driver="GeoJSON")
        g[keepcols + ["area_km2"]].to_csv(out / f"{stem}.csv", index=False)

    bcols = ["name", "n_cells", "mean_mm_h", "max_mm_h", "p90_mm_h", "area_ge_mod_pct", "area_ge_heavy_pct", "level"]
    dump(basins,  "tupann_basins",  bcols)
    dump(bairros, "tupann_bairros", bcols)

    # warnings — every zone at LARANJA/VERMELHO, worst first
    warns = []
    for scale, gdf in [("bacia", basins), ("bairro", bairros)]:
        for _, r in gdf.iterrows():
            if r["level"] in ("LARANJA", "VERMELHO"):
                warns.append(dict(scale=scale, name=str(r["name"]), level=str(r["level"]),
                                  p90_mm_h=round(float(r["p90_mm_h"]), 2), max_mm_h=round(float(r["max_mm_h"]), 2),
                                  area_ge_heavy_pct=round(float(r["area_ge_heavy_pct"]), 1)))
    warns.sort(key=lambda w: (w["level"] != "VERMELHO", -w["p90_mm_h"]))
    n_red = sum(w["level"] == "VERMELHO" for w in warns)
    n_ora = sum(w["level"] == "LARANJA" for w in warns)
    (out / "tupann_warnings.json").write_text(json.dumps(dict(
        issue_utc=issue_utc, lead_min=lead_min, model=model,
        tau_mod=tau_mod, tau_heavy=tau_heavy, n_red=n_red, n_orange=n_ora,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        phase="teste", note="Nowcast experimental — nao e alerta oficial da Defesa Civil.",
        warnings=warns), ensure_ascii=False), encoding="utf-8")

    # meta
    (out / "tupann_meta.json").write_text(json.dumps(dict(
        model=model, issue_utc=issue_utc, lead_min=lead_min,
        tau_mod=tau_mod, tau_heavy=tau_heavy,
        grid_cells=int(len(grid_pts)), grid_cells_total=int(len(pts)), grid_stride=int(stride),
        grid_thinned=bool(stride > 1), n_basins=int(len(basins)), n_bairros=int(len(bairros)),
        n_red=n_red, n_orange=n_ora, grid_res_km=2.0,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source="satellite nowcast (TUPANN) + calibrated operating point (nb 05e / 07b §14)",
        phase="teste", disclaimer="Produto experimental de pesquisa; nao substitui a Defesa Civil."),
        ensure_ascii=False), encoding="utf-8")

    print(f"[build_tupann_nowcast] {model} issue={issue_utc} +{lead_min}min | "
          f"grid {len(pts)} cells | basins {len(basins)} | bairros {len(bairros)} | "
          f"RED {n_red} ORANGE {n_ora} | tau_mod {tau_mod} tau_heavy {tau_heavy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
