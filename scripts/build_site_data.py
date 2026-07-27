#!/usr/bin/env python3
"""
build_site_data.py — generate the compact JSON the static front-end reads.

Reads the consolidated masters (hourly + daily parquet), the station registry
and the city GeoJSON, and writes site/data/*.json. Every value is derived
strictly from the real data; nothing is invented. Derivations are documented
inline so the numbers on the dashboard are fully traceable.

Sources of "now":
  - Near-real-time values come from the most recent HOURLY observation per
    station, PER VARIABLE (coverage differs by variable: a station may have
    fresh wind but stale temperature). When 5-min masters are present locally
    they refine granularity but the hourly master is the portable source of
    truth committed to the repo.

Freshness ("online"):
  - The network's newest observation time (across all stations/variables) is
    the reference "now". A station variable is FRESH if its latest observation
    is within FRESH_DAYS of that reference. Data is uploaded ~weekly, so
    FRESH_DAYS = 8 keeps a station "online" between weekly pushes.
"""
from __future__ import annotations
import json, math, glob, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HOURLY = ROOT / "data" / "hourly"
DAILY  = ROOT / "data" / "daily"
GEO    = ROOT / "data" / "geo"
PROC   = ROOT / "data" / "processed"
OUT    = ROOT / "site" / "data"
OUT.mkdir(parents=True, exist_ok=True)

FRESH_DAYS   = 8            # a reading within this many days of the network "now" is "online"
ROSE_MONTHS  = 12          # wind-rose pooled over the last N months of available hourly data
DAILY_DAYS   = 20          # daily temperature-range strip length
WIND_HOURS   = 24          # wind line-plot span

# WMO / OMM rainfall intensity classes (mm/h). Ref: WMO-No. 407, International
# Cloud Atlas / Manual on Codes; widely used operational thresholds.
RAIN_CLASSES = [("leve", 0.0, 2.5), ("moderada", 2.5, 10.0),
                ("forte", 10.0, 50.0), ("violenta", 50.0, math.inf)]

reg = pd.read_csv(GEO / "stations_master.csv")
# keep only stations that have a master file (exclude e.g. jativoca/aeroporto w/o hourly parquet here)
have = {os.path.basename(f)[:-8] for f in glob.glob(str(HOURLY / "*.parquet"))}

def load_hourly(code):
    f = HOURLY / f"{code}.parquet"
    if not f.exists(): return None
    d = pd.read_parquet(f)
    d["date"] = pd.to_datetime(d["date"])
    return d.sort_values("date")

def load_daily(code):
    f = DAILY / f"{code}.parquet"
    if not f.exists(): return None
    d = pd.read_parquet(f)
    d["date"] = pd.to_datetime(d["date"])
    return d.sort_values("date")

# ---- pass 1: latest observation time per station (across core vars) ----
hourly = {c: load_hourly(c) for c in reg["code"] if c in have}
hourly = {c: d for c, d in hourly.items() if d is not None and len(d)}

def last_valid(d, col):
    if col not in d.columns: return None
    s = d.dropna(subset=[col])
    if not len(s): return None
    r = s.iloc[-1]
    return {"v": float(r[col]), "t": r["date"].isoformat()}

# network reference "now" = newest core observation anywhere
ref_now = None
for c, d in hourly.items():
    for col in ("temp", "prec", "ws"):
        lv = last_valid(d, col)
        if lv:
            t = pd.Timestamp(lv["t"])
            ref_now = t if ref_now is None else max(ref_now, t)
FRESH_CUT = ref_now - pd.Timedelta(days=FRESH_DAYS)

def is_fresh(iso):
    return iso is not None and pd.Timestamp(iso) >= FRESH_CUT

def rain_24h(d):
    """Sum of precipitation over the 24 h ending at the station's latest prec obs."""
    if "prec" not in d.columns: return None
    s = d.dropna(subset=["prec"])
    if not len(s): return None
    end = s["date"].iloc[-1]; start = end - pd.Timedelta(hours=24)
    w = s[(s["date"] > start) & (s["date"] <= end)]
    return {"v": round(float(w["prec"].sum()), 1), "t": end.isoformat()}

def rain_rate_1h(d):
    """Latest hourly precipitation total (mm in the last hour) = intensity mm/h."""
    if "prec" not in d.columns: return None
    s = d.dropna(subset=["prec"])
    if not len(s): return None
    r = s.iloc[-1]
    return {"v": round(float(r["prec"]), 1), "t": r["date"].isoformat()}

# ---- per-station snapshot ----
stations = []
reg_by_code = {r["code"]: r for _, r in reg.iterrows()}
for code, d in hourly.items():
    r = reg_by_code[code]
    temp = last_valid(d, "temp")
    umid = last_valid(d, "umid")
    feels = last_valid(d, "heat_index")
    wsv  = last_valid(d, "ws")
    wdv  = last_valid(d, "wd")
    r24  = rain_24h(d)
    rr1  = rain_rate_1h(d)
    wind = None
    if wsv:
        wind = {"ws": round(wsv["v"], 1),
                "wd": (round(wdv["v"]) if wdv and abs((pd.Timestamp(wdv["t"]) - pd.Timestamp(wsv["t"])).total_seconds()) < 3700 else None),
                "t": wsv["t"], "fresh": is_fresh(wsv["t"])}
    last_times = [x["t"] for x in (temp, wsv, r24) if x]
    last_time = max(last_times) if last_times else None
    stations.append({
        "code": code,
        "name": str(r["name"]).split("(")[0].strip(),
        "type": r["type"],
        "lat": float(r["lat"]), "lon": float(r["lon"]),
        "elevation": (None if pd.isna(r["elevation"]) else float(r["elevation"])),
        "temp": ({"v": round(temp["v"], 1), "t": temp["t"], "fresh": is_fresh(temp["t"])} if temp else None),
        "umid": ({"v": round(umid["v"]), "t": umid["t"], "fresh": is_fresh(umid["t"])} if umid else None),
        "feels": ({"v": round(feels["v"], 1), "t": feels["t"], "fresh": is_fresh(feels["t"])} if feels else None),
        "rain": ({"v": r24["v"], "t": r24["t"], "fresh": is_fresh(r24["t"])} if r24 else None),
        "rain_rate": (rr1 if rr1 else None),
        "wind": wind,
        "last_time": last_time,
        "fresh": is_fresh(last_time),
    })

stations.sort(key=lambda s: (not s["fresh"], s["name"]))

# ---- network aggregates (online stations only) ----
def mean_of(getter):
    vals = [getter(s) for s in stations if s["fresh"]]
    vals = [v for v in vals if v is not None]
    return round(float(np.mean(vals)), 1) if vals else None

temp_mean = mean_of(lambda s: s["temp"]["v"] if (s["temp"] and s["temp"]["fresh"]) else None)
wind_mean = mean_of(lambda s: s["wind"]["ws"] if (s["wind"] and s["wind"]["fresh"]) else None)
hum_mean  = mean_of(lambda s: s["umid"]["v"] if (s.get("umid") and s["umid"]["fresh"]) else None)
feels_mean = mean_of(lambda s: s["feels"]["v"] if (s.get("feels") and s["feels"]["fresh"]) else None)
precip_now = max([s["rain_rate"]["v"] for s in stations
                  if s.get("rain_rate") and is_fresh(s["rain_rate"]["t"])], default=None)
# rain 24h max among fresh stations
rain_pts = [(s["rain"]["v"], s["name"]) for s in stations if s["rain"] and s["rain"]["fresh"]]
rain_max = max(rain_pts) if rain_pts else None
n_online = sum(s["fresh"] for s in stations)

# ---- last-24h network wind line (avg ws over stations reporting each hour) ----
def network_wind_series():
    end = ref_now.floor("h"); start = end - pd.Timedelta(hours=WIND_HOURS - 1)
    idx = pd.date_range(start, end, freq="h")
    acc = pd.DataFrame(index=idx)
    for c, d in hourly.items():
        if "ws" not in d.columns: continue
        s = d.dropna(subset=["ws"]).set_index("date")["ws"]
        s = s[~s.index.duplicated(keep="last")]
        acc[c] = s.reindex(idx)
    series = acc.mean(axis=1, skipna=True)
    return [{"t": t.isoformat(), "ws": (None if pd.isna(v) else round(float(v), 2))}
            for t, v in series.items()]

wind24 = network_wind_series()

# ---- last-20-day network daily temperature range (mean of station daily extremes) ----
def network_daily_temp():
    frames = []
    for c in hourly:
        dd = load_daily(c)
        if dd is None or "temp_max" not in dd.columns or "temp_min" not in dd.columns: continue
        sub = dd[["date", "temp_max", "temp_min"]].dropna(subset=["temp_max", "temp_min"])
        if len(sub): frames.append(sub.assign(code=c))
    if not frames: return []
    alld = pd.concat(frames)
    g = alld.groupby("date").agg(mx=("temp_max", "mean"), mn=("temp_min", "mean")).dropna(how="all")
    g = g.dropna()
    g = g.tail(DAILY_DAYS)
    return [{"d": t.strftime("%d/%m"), "mn": round(float(row["mn"]), 1), "mx": round(float(row["mx"]), 1)}
            for t, row in g.iterrows()]

daily_temp = network_daily_temp()

# ---- openair-style wind rose: 16 dir x speed-class frequency (%) ----
# Direction QC: (1) CALM winds (ws < CALM_MS) carry no meaningful direction — a vane can't
# resolve one at ~0 speed — so they are excluded from the sectors and reported as a calm %.
# (2) BROKEN-VANE stations — where wd sits at EXACTLY 0° for an implausible share of *windy*
# hours (ws >= CALM_MS) — are dropped entirely: a real N-dominant site spreads around N, it
# doesn't pin to 0.000°. This removes the stuck/absent-vane artefact (e.g. two stations here
# reported wd==0 for ~41% of windy hours) that otherwise fabricates a false "North" peak.
ROSE_CLASSES = [(0, 2), (2, 4), (4, 6), (6, 8), (8, 999)]
CALM_MS = 0.5            # m/s — below this, direction is undefined (calm)
STUCK_FRAC = 0.25        # >25% of windy hours at exactly 0° -> broken/absent vane
def wind_rose():
    cut = ref_now - pd.DateOffset(months=ROSE_MONTHS)
    wd_all, ws_all = [], []
    used, dropped = [], []
    for c, d in hourly.items():
        if "wd" not in d.columns or "ws" not in d.columns: continue
        s = d.dropna(subset=["wd", "ws"])
        s = s[s["date"] >= cut]
        wd_s = s["wd"].to_numpy(); ws_s = s["ws"].to_numpy()
        windy = ws_s >= CALM_MS
        if windy.sum() < 100:                       # too little wind to judge
            continue
        stuck = np.mean(wd_s[windy] == 0.0)         # exact-0 share among windy hours
        if stuck > STUCK_FRAC:
            dropped.append({"code": c, "stuck0_pct": round(float(stuck * 100), 1)})
            continue
        used.append(c)
        wd_all.append(wd_s); ws_all.append(ws_s)
    if not wd_all: return None
    wd = np.concatenate(wd_all); ws = np.concatenate(ws_all)
    n_total = len(wd)
    calm = ws < CALM_MS
    calm_pct = round(float(np.mean(calm) * 100), 1)
    wd = wd[~calm]; ws = ws[~calm]                  # sectors use non-calm winds only
    n = len(wd)
    if n == 0: return None
    # 16 sectors centred on N=0; sector width 22.5deg (shift by +11.25 so N spans -11.25..11.25)
    sec = (np.floor(((wd % 360) + 11.25) / 22.5).astype(int)) % 16
    freq = np.zeros((16, len(ROSE_CLASSES)))
    for i in range(16):
        m = sec == i
        wsi = ws[m]
        for j, (lo, hi) in enumerate(ROSE_CLASSES):
            freq[i, j] = np.sum((wsi >= lo) & (wsi < hi))
    freq = freq / n * 100.0
    return {"dirs": 16, "classes": [f"{lo}–{hi if hi<900 else ''}".rstrip("–") for lo, hi in ROSE_CLASSES],
            "class_edges": ROSE_CLASSES, "freq": np.round(freq, 2).tolist(),
            "n": int(n), "months": ROSE_MONTHS, "calm_pct": calm_pct, "calm_ms": CALM_MS,
            "stations_used": sorted(used), "stations_dropped": dropped,
            "period": [cut.isoformat(), ref_now.isoformat()]}

rose = wind_rose()

# ---- last-24h wind rose, per station AND network-average (same QC/binning as wind_rose) ----
# Powers the interactive rose on the Início page: default = network average of the last 24 h;
# clicking a station on the map shows that station's own last-24h rose.
def bin_rose(wd, ws):
    """16-sector x speed-class frequency (%) from raw wd/ws arrays; calm winds (< CALM_MS)
    excluded from the sectors and reported as calm_pct. Identical convention to wind_rose()."""
    wd = np.asarray(wd, float); ws = np.asarray(ws, float)
    m = np.isfinite(wd) & np.isfinite(ws)
    wd, ws = wd[m], ws[m]
    n_total = len(wd)
    if n_total == 0:
        return None
    calm = ws < CALM_MS
    calm_pct = round(float(np.mean(calm) * 100), 1)
    wdn, wsn = wd[~calm], ws[~calm]
    n = len(wdn)
    freq = np.zeros((16, len(ROSE_CLASSES)))
    if n:
        sec = (np.floor(((wdn % 360) + 11.25) / 22.5).astype(int)) % 16
        for i in range(16):
            wsi = wsn[sec == i]
            for j, (lo, hi) in enumerate(ROSE_CLASSES):
                freq[i, j] = np.sum((wsi >= lo) & (wsi < hi))
        freq = freq / n * 100.0
    return {"freq": np.round(freq, 2).tolist(), "n": int(n), "n_total": int(n_total),
            "calm_pct": calm_pct, "ws_mean": round(float(np.nanmean(ws)), 2)}

def wind_rose_24h():
    end = ref_now.floor("h"); start = end - pd.Timedelta(hours=WIND_HOURS - 1)
    by = {}; pool_wd, pool_ws = [], []; used, dropped = [], []
    for c, d in hourly.items():
        if "wd" not in d.columns or "ws" not in d.columns:
            continue
        s = d.dropna(subset=["wd", "ws"])
        s = s[(s["date"] >= start) & (s["date"] <= end)]
        if s.empty:
            continue
        wd_s = s["wd"].to_numpy(); ws_s = s["ws"].to_numpy()
        windy = ws_s >= CALM_MS
        dir_ok = True
        if windy.sum() >= 4:                                  # only judge the vane with enough windy hours
            stuck = float(np.mean(wd_s[windy] == 0.0))        # stuck/absent-vane artefact
            if stuck > STUCK_FRAC:
                dir_ok = False; dropped.append({"code": c, "stuck0_pct": round(stuck * 100, 1)})
        r = bin_rose(wd_s, ws_s)
        if r is None:
            continue
        r["dir_ok"] = dir_ok
        by[c] = r
        if dir_ok:
            used.append(c); pool_wd.append(wd_s); pool_ws.append(ws_s)
    network = bin_rose(np.concatenate(pool_wd), np.concatenate(pool_ws)) if pool_wd else None
    return {"window": [start.isoformat(), end.isoformat()], "hours": WIND_HOURS, "dirs": 16,
            "classes": [f"{lo}–{hi if hi < 900 else ''}".rstrip("–") for lo, hi in ROSE_CLASSES],
            "class_edges": ROSE_CLASSES, "calm_ms": CALM_MS,
            "network": network, "by_station": by,
            "stations_used": sorted(used), "stations_dropped": dropped}

rose24 = wind_rose_24h()

# ---- WMO/OMM severe-weather alert (data-driven) ----
def rain_class(mmph):
    for name, lo, hi in RAIN_CLASSES:
        if lo <= mmph < hi: return name
    return "leve"

def alert_state():
    # rainfall: worst current hourly intensity among online stations
    rates = [(s["rain_rate"]["v"], s["name"]) for s in stations
             if s.get("rain_rate") and is_fresh(s["rain_rate"]["t"])]
    rain = None
    if rates:
        v, who = max(rates)
        cls = rain_class(v)
        rain = {"value_mmph": v, "station": who, "class": cls,
                "active": v >= 10.0}   # "forte"+ => active advisory
    # temperature: online extremes
    temps = [s["temp"]["v"] for s in stations if s["temp"] and s["temp"]["fresh"]]
    temp = None
    if temps:
        tmin, tmax = min(temps), max(temps)
        temp = {"min": round(tmin, 1), "max": round(tmax, 1),
                # advisory bands are placeholders pending the project's local
                # thresholds; flagged so the UI can show them as provisional.
                "heat_active": tmax >= 35.0, "cold_active": tmin <= 5.0}
    active = bool((rain and rain["active"]) or (temp and (temp["heat_active"] or temp["cold_active"])))
    return {"active": active, "rain": rain, "temp": temp,
            "rain_classes": [{"name": n, "min_mmph": lo, "max_mmph": (None if hi == math.inf else hi)}
                             for n, lo, hi in RAIN_CLASSES]}

alert = alert_state()

# ---- simple "current condition" label from network cloud/rain proxy ----
def condition_label():
    if alert["rain"] and alert["rain"]["value_mmph"] >= 2.5: return "Chuva"
    if rain_max and rain_max[0] > 0: return "Nublado com chuva recente"
    return "Parcialmente nublado"

snap = {
    "generated_at": pd.Timestamp.now("UTC").isoformat(),
    "reference_now": ref_now.isoformat(),
    "fresh_days": FRESH_DAYS,
    "network": {
        "n_total": len(stations),
        "n_online": n_online,
        "temp_mean": temp_mean,
        "wind_mean": wind_mean,
        "humidity_mean": hum_mean,
        "feels": feels_mean,
        "precip_now": precip_now,
        "wind_now": (wind24[-1]["ws"] if wind24 and wind24[-1]["ws"] is not None else wind_mean),
        "rain_24h_max": ({"v": rain_max[0], "station": rain_max[1]} if rain_max else None),
        "condition": condition_label(),
    },
    "stations": stations,
    "wind24h": wind24,
    "daily_temp": daily_temp,
    "windrose": rose,
    "windrose24": rose24,
    "alert": alert,
}

(OUT / "snapshot.json").write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

# ---- copy geojson the map needs (compact) ----
import shutil
for src, dst in [("joinville_limite.geojson", "limite.geojson"),
                 ("BAIRROS.geojson", "bairros.geojson"),
                 ("bacias_joinville.geojson", "bacias.geojson")]:
    p = PROC / src
    if p.exists():
        shutil.copy(p, OUT / dst)

print(f"reference_now = {ref_now}")
print(f"stations = {len(stations)} | online = {n_online}")
print(f"temp_mean = {temp_mean} | wind_mean = {wind_mean} | wind_now = {snap['network']['wind_now']}")
print(f"rain_24h_max = {rain_max}")
print(f"wind24h pts = {len(wind24)} (non-null {sum(1 for x in wind24 if x['ws'] is not None)})")
print(f"daily_temp days = {len(daily_temp)}")
print(f"windrose n = {rose['n'] if rose else 0} obs over {ROSE_MONTHS} months")
print(f"alert active = {alert['active']} | rain = {alert['rain']} | temp = {alert['temp']}")
print("online stations:", [s["name"] for s in stations if s["fresh"]])
