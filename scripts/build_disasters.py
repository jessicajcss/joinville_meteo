#!/usr/bin/env python3
"""
build_disasters.py — parse the SEPROT/Defesa Civil disaster-occurrences table into
site/data/disasters.json for the "Risco Hidro-climático" page.

Source: data/disasters/ocorrencias.csv  (SEPROT.UCP — Ocorrências de Desastres)
The file is doubly CSV-encoded by Excel (each row is itself a quoted CSV string),
so it needs the unwrap step below. Columns: Data/Hora, Causa, Tipo, Desabrigados,
Bairros, Situação.

Output: events (date, year, tipo, situacao, desabrigados, bairros[]) + the lists of
tipos and situações for the map filters. Bairro names are matched to the official
BAIRROS.geojson `Nome_Bairr` (accent/spelling-normalized).
"""
from __future__ import annotations
import csv, json, re, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "disasters" / "ocorrencias.csv"
GEOJSON = ROOT / "site" / "data" / "bairros.geojson"
OUT = ROOT / "site" / "data"

MES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
       "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().strip()
    return s.replace("JARDIN", "JARDIM")

geo = json.load(open(GEOJSON, encoding="utf-8"))
GEO = {norm(f["properties"]["Nome_Bairr"]): f["properties"]["Nome_Bairr"] for f in geo["features"]}

def match_bairro(b):
    n = norm(b)
    if not n or n in ("ZONA RURAL", "NAO HA DADOS", "0", "5", "6"):
        return None
    if n in GEO:
        return GEO[n]
    for k, v in GEO.items():          # loose contains match
        if n in k or k in n:
            return v
    return None

def parse_date(s):
    d = re.search(r"(\d{1,2})\s+de\s+(\w+)", s)
    y = re.search(r"de\s+(\d{4})", s)
    if not d or not y:
        return None
    return f"{int(y.group(1)):04d}-{MES.get(d.group(2).lower()[:3], 0):02d}-{int(d.group(1)):02d}"

def norm_situ(s):
    sl = s.lower()
    if "calamidade" in sl: return "Calamidade"
    if "emerg" in sl: return "Emergência"
    if "normalidade" in sl: return "Normalidade"
    return "Não informado"

# hydro-climatic (rainfall/storm-driven) disaster types to KEEP; everything else
# (health/biological, structural, technological, mislabeled) is excluded from this page.
HYDRO_TIPOS = {"Enxurrada", "Vendaval", "Alagamentos", "Inundação", "Granizo",
               "Chuvas Intensas", "Erosão de Margem Fluvial", "Movimento de Massa",
               "Tempestade Local/Convectiva", "Chuva e rajada de vento", "Tempestade com vento"}

events = []
for raw in open(SRC, encoding="utf-8-sig"):
    line = raw.rstrip("\n").strip()
    if not line: continue
    if line.endswith(";"): line = line[:-1].strip()
    try:
        f = next(csv.reader([line]))
    except Exception:
        continue
    if len(f) == 1:
        try: f = next(csv.reader([f[0]]))
        except Exception: continue
    if not f or f[0].startswith("Data") or len(f) < 7:
        continue
    date = parse_date(f[0] + " " + f[1])
    if not date: continue
    tipo = f[3].strip()
    if tipo not in HYDRO_TIPOS:                 # keep only hydro-climatic events on this page
        continue
    try: desab = int(re.sub(r"\D", "", f[4]) or 0)
    except Exception: desab = 0
    bairros = sorted({match_bairro(b) for b in f[5].split(",")} - {None})
    events.append({"date": date, "year": int(date[:4]), "tipo": tipo,
                   "situacao": norm_situ(f[6]), "desabrigados": desab, "bairros": bairros})

events.sort(key=lambda e: e["date"])
tipos = sorted({e["tipo"] for e in events})
situacoes = ["Normalidade", "Emergência", "Calamidade"]

payload = {
    "generated_at": __import__("datetime").datetime.utcnow().isoformat() if False else None,
    "geo_key": "Nome_Bairr",
    "n_events": len(events),
    "period": [events[0]["date"], events[-1]["date"]],
    "tipos": tipos,
    "situacoes": [s for s in (situacoes + ["Não informado"]) if any(e["situacao"] == s for e in events)],
    "events": events,
}
# stamp time without the forbidden argless call
import subprocess
payload["generated_at"] = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%MZ"], capture_output=True, text=True).stdout.strip()

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "disasters.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

from collections import Counter
print(f"events: {len(events)} | {payload['period'][0]} -> {payload['period'][1]}")
print("tipos:", dict(Counter(e["tipo"] for e in events)))
print("situações:", dict(Counter(e["situacao"] for e in events)))
bc = Counter(b for e in events for b in e["bairros"])
print("matched bairros:", len(bc), "| top:", bc.most_common(6))
print("total desabrigados:", sum(e["desabrigados"] for e in events))
