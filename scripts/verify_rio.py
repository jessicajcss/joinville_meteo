#!/usr/bin/env python3
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "file://" + str(Path("/root/joinville-meteo-dashboard/rio_standalone.html"))
OUT = Path("/root/joinville-meteo-dashboard/_verify"); OUT.mkdir(exist_ok=True)
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 2000})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)))
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(1200)

    def opts(sel):
        return pg.eval_on_selector(sel, "el=>Array.from(el.options).map(o=>o.value+'|'+o.textContent)")
    def stnames(sel):
        return pg.eval_on_selector(sel, "el=>Array.from(el.options).map(o=>o.textContent)")

    report = {}
    # perfil mensal — station list (estuary label) + default year list
    report["level_station_opts"] = stnames("#selStL")
    report["level_year_default(flotflux)"] = opts("#selYearL")

    # switch perfil mensal to Iate Clube (estuary) -> years should include 2025
    val = pg.eval_on_selector("#selStL", "el=>{let o=[...el.options].find(o=>o.textContent.includes('Iate'));return o?o.value:null;}")
    pg.select_option("#selStL", val)
    pg.wait_for_timeout(500)
    report["level_year_iateclube"] = opts("#selYearL")
    report["level_sub_iateclube"] = pg.text_content("#lsub")
    report["qcLevel_iateclube"] = pg.text_content("#qcLevel")

    # heatmap: default (flotflux) years + estuary years + captions
    report["hm_year_default(flotflux)"] = opts("#selYearH")
    hval = pg.eval_on_selector("#selStH", "el=>{let o=[...el.options].find(o=>o.textContent.includes('Iate'));return o?o.value:null;}")
    pg.select_option("#selStH", hval)
    pg.wait_for_timeout(500)
    report["hm_year_iateclube"] = opts("#selYearH")
    report["hm_capt_iateclube"] = pg.text_content("#hcapt")
    report["hm_qc_iateclube"] = pg.text_content("#qcHour")

    # daily years for a station whose data extends past 2024 (flotflux data_years to 2026)
    report["daily_year_default(flotflux)"] = opts("#selYearD")

    # screenshots of the level cards
    for cid, fn in [("#dumbbell", "01_level_monthly"), ("#hourCard", "02_heatmap"),
                    ("#dailyCard", "03_daily")]:
        try:
            pg.locator(cid).scroll_into_view_if_needed(); pg.wait_for_timeout(300)
            pg.locator(cid).screenshot(path=str(OUT / f"{fn}.png"))
        except Exception as e:
            report[f"shot_{fn}_err"] = str(e)
    # full page
    pg.screenshot(path=str(OUT / "00_full.png"), full_page=True)
    b.close()

report["JS_ERRORS"] = errors
print(json.dumps(report, ensure_ascii=False, indent=1))
