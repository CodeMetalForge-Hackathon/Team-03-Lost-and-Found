"""Playwright screenshots of every new screen -> zoom/screenshots/. Usage: ~/forge/.venv/bin/python shots.py"""
import asyncio
from playwright.async_api import async_playwright
S = "screenshots/"
SHOTS = [
 ("air_noaa_helene.png", "http://localhost:8150/air", None, 3000),
 ("air_noaa_helene_zoom_detections.png", "http://localhost:8150/air", "view.cx=600;view.cy=6100;view.mpp=0.6;draw();", 3500),
 ("air_noaa_ian_relief_captions.png", "http://localhost:8150/air", "document.getElementById('scene').value='ian'; pick('ian').then(()=>{layers.depth=1;layers.cap=1;draw();});", 4000),
 ("air_map_forming_stitch.png", "http://localhost:8150/air", "document.getElementById('tStitch').click();", 9000),
 ("water_8150.png", "http://localhost:8150/water", None, 3500),
 ("cop_air_stitch.png", "http://localhost:8143", "document.getElementById('baseSel').value='stitch'; dT=DR.track.duration_s; view={e:(ORTHO.sw_en[0]+ORTHO.ne_en[0])/2,n:(ORTHO.sw_en[1]+ORTHO.ne_en[1])/2,s:1.6}; SHOWF.aerial=1; SHOWF.aerial_sim=1; load();", 5000),
 ("cop_water_sonar.png", "http://localhost:8143", "wPing=ZM.water.n_pings; document.getElementById('wGo').onclick(); SHOWF.sonar=1; SHOWF.water=1; load();", 5000),
 ("cop_nba_overview.png", "http://localhost:8143", "dT=DR.track.duration_s; wPing=ZM.water.n_pings; view={e:2500,n:-4500,s:0.05}; load();", 5000),
 ("cop_noaa_inset.png", "http://localhost:8143", "document.getElementById('noaaBtn').click();", 6000),
]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for name, url, js, wait in SHOTS:
            pg = await b.new_page(viewport={"width": 1400, "height": 900}); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(url); await pg.wait_for_timeout(2500)
            if js: await pg.evaluate(js)
            await pg.wait_for_timeout(wait); await pg.screenshot(path=S + name); await pg.close()
            print(name, "errors:", errs)
        await b.close()
asyncio.run(main())
