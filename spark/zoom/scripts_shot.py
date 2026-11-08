import sys, asyncio
from playwright.async_api import async_playwright
async def main(url, out, w=1400, h=900, wait=2500, js=None):
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(viewport={"width": w, "height": h})
        await pg.goto(url); await pg.wait_for_timeout(wait)
        if js: await pg.evaluate(js); await pg.wait_for_timeout(wait)
        await pg.screenshot(path=out); await b.close()
asyncio.run(main(sys.argv[1], sys.argv[2], js=sys.argv[3] if len(sys.argv) > 3 else None))
