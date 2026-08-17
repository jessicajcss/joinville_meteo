#!/usr/bin/env python3
"""
push_tupann_field.py  —  the UPSTREAM (GPU / ONNX-CPU) half of the TUPANN nowcast loop.

Run this WHERE the model runs (Colab GPU, a small VM, or ONNX on CPU), right after you have the
calibrated TUPANN / U-Net 2 km nowcast field for the current issue time. It writes the field as
site/data/tupann/incoming/field_latest.npz and (optionally) git-commits + pushes it, which triggers
the .github/workflows/forecast-tupann.yml job to build the dashboard products.

It does NOT run the model — you pass in the field + its 2 km grid. Keeping inference upstream is what
lets the dashboard side stay pure-CPU. See TUPANN_NOWCAST.md for the full loop.

Usage (from your inference notebook/script):
    from push_tupann_field import publish
    publish(field2d, lat2d, lon2d,
            issue_utc="2026-02-21T18:00:00Z", lead_min=30,
            model="U-Net 07b (calibrated)", tau_mod=1.4, tau_heavy=4.0,
            repo_root=".", git_push=False)
"""
from __future__ import annotations
import json, subprocess
from pathlib import Path
import numpy as np


def publish(field2d, lat2d, lon2d, *, issue_utc, lead_min, model="TUPANN",
            tau_mod=1.4, tau_heavy=4.0, repo_root=".", git_push=False):
    field2d = np.asarray(field2d, "float32")
    lat2d = np.asarray(lat2d, "float32")
    lon2d = np.asarray(lon2d, "float32")
    assert field2d.shape == lat2d.shape == lon2d.shape, "field2d / lat2d / lon2d must share shape"

    inc = Path(repo_root) / "site" / "data" / "tupann" / "incoming"
    inc.mkdir(parents=True, exist_ok=True)
    meta = dict(issue_utc=issue_utc, lead_min=int(lead_min), model=model,
                tau_mod=float(tau_mod), tau_heavy=float(tau_heavy))
    out = inc / "field_latest.npz"
    np.savez(out, field2d=field2d, lat2d=lat2d, lon2d=lon2d, meta_json=json.dumps(meta))
    print(f"[push_tupann_field] wrote {out}  ({field2d.shape}, {field2d.nbytes/1e3:.0f} kB)  meta={meta}")

    if git_push:
        try:
            subprocess.run(["git", "-C", repo_root, "add", str(out)], check=True)
            subprocess.run(["git", "-C", repo_root, "commit", "-m",
                            f"TUPANN nowcast field {issue_utc} +{lead_min}min"], check=True)
            subprocess.run(["git", "-C", repo_root, "push"], check=True)
            print("[push_tupann_field] pushed — the forecast-tupann Action will build the products.")
        except subprocess.CalledProcessError as e:
            print("[push_tupann_field] git step failed (push manually):", e)
    return out


if __name__ == "__main__":
    # tiny self-demo: a synthetic field over a coarse grid (no model needed)
    import numpy as _np
    H = W = 64
    lons = _np.linspace(-49.2, -48.7, W); lats = _np.linspace(-26.1, -26.5, H)
    lo, la = _np.meshgrid(lons, lats)
    fld = 0.4 + 6.0 * _np.exp(-(((lo + 48.98) ** 2 + (la + 26.16) ** 2) / (2 * 0.04 ** 2)))
    publish(fld, la, lo, issue_utc="2026-02-21T18:00:00Z", lead_min=30,
            model="demo", tau_mod=1.4, tau_heavy=4.0, repo_root="/tmp/_tupann_demo_repo", git_push=False)
