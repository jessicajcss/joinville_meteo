#!/usr/bin/env python3
"""Bundle site/rio.html into a single self-contained HTML file.

Inlines app.css + Leaflet css/js, base64-embeds the three logo/hero images, and
embeds river.json + every data/river/<code>.json, monkeypatching fetch() so the
page runs with no server. Nothing about the data is altered — only transport.
"""
from __future__ import annotations
import base64, json, re, sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else (Path.cwd() / "rio_standalone.html")

html = (SITE / "rio.html").read_text(encoding="utf-8")

def read(p): return (SITE / p).read_text(encoding="utf-8")
def b64(p):
    raw = (SITE / p).read_bytes()
    ext = Path(p).suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}.get(ext, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

# 1) inline stylesheets
html = html.replace('<link rel="stylesheet" href="assets/css/app.css">',
                    "<style>\n" + read("assets/css/app.css") + "\n</style>")
html = html.replace('<link rel="stylesheet" href="assets/vendor/leaflet/leaflet.css">',
                    "<style>\n" + read("assets/vendor/leaflet/leaflet.css") + "\n</style>")

# 2) base64 images
for img in ["assets/img/windmill.png", "assets/img/udesc.png", "assets/img/lacia.jpg"]:
    html = html.replace(img, b64(img))

# 3) embed data + fetch shim, then inline leaflet.js
data = {"data/river.json": json.loads(read("data/river.json"))}
if (SITE / "data" / "enso.json").exists():
    data["data/enso.json"] = json.loads(read("data/enso.json"))
for f in sorted((SITE / "data" / "river").glob("*.json")):
    data[f"data/river/{f.name}"] = json.loads(f.read_text(encoding="utf-8"))

shim = ("<script>\n(function(){const D="
        + json.dumps(data, ensure_ascii=False)
        + ";\nconst _f=window.fetch?window.fetch.bind(window):null;"
        "window.fetch=function(u,o){const k=String(u).replace(/^\\.?\\//,'');"
        "if(k in D){return Promise.resolve({ok:true,json:()=>Promise.resolve(D[k]),"
        "text:()=>Promise.resolve(JSON.stringify(D[k]))});}"
        "return _f?_f(u,o):Promise.reject(new Error('offline: '+u));};})();\n</script>\n")

leaflet_js = "<script>\n" + read("assets/vendor/leaflet/leaflet.js") + "\n</script>"
html = html.replace('<script src="assets/vendor/leaflet/leaflet.js"></script>', shim + leaflet_js)

OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB)  · {len(data)} data blobs")
