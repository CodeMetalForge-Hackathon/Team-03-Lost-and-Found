"""Playwright screenshot helper: python shot.py URL OUT.png [wait_ms] [js_to_run_before]"""
import sys, asyncio
from playwright.async_api import async_playwright
async def main(url, out, wait=1500, js=None, w=1400, h=900):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": w, "height": h})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append("console:" + m.text) if m.type == "error" else None)
        await pg.goto(url); await pg.wait_for_timeout(wait)
        if js: await pg.evaluate(js); await pg.wait_for_timeout(800)
        await pg.screenshot(path=out, full_page=True); await b.close()
        print("errors:", errs)
a = sys.argv
asyncio.run(main(a[1], a[2], int(a[3]) if len(a) > 3 else 1500, a[4] if len(a) > 4 else None))
