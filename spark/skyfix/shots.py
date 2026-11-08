"""Playwright screenshots of /, /?hud=1, /demo into screenshots/. Usage: python shots.py [base_url]"""
import sys, pathlib, time
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8130"
OUT = pathlib.Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(exist_ok=True)
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    # phone: night synthetic demo -> fix
    pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg.on("pageerror", lambda e: errors.append(f"/: {e}"))
    pg.goto(BASE + "/"); pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "phone_home.png"))
    pg.select_option("#demoSel", "synth:boston_az150_alt35"); pg.click("#useDemo")
    pg.wait_for_function("document.getElementById('big').textContent.includes('BRG')", timeout=60000); pg.wait_for_timeout(500)
    pg.screenshot(path=str(OUT / "phone_night_fix.png"), full_page=True)
    # phone: day CH1
    pg.click("#mDay"); pg.wait_for_timeout(600)
    opts = pg.eval_on_selector_all("#demoSel option", "os=>os.map(o=>o.value).filter(v=>v.startsWith('ch1:'))")
    pg.select_option("#demoSel", opts[0]); pg.click("#useDemo")
    pg.wait_for_function("document.getElementById('big').textContent.includes('BRG')", timeout=120000); pg.wait_for_timeout(1200)
    pg.screenshot(path=str(OUT / "phone_day_fix.png"), full_page=True)
    # breadcrumb (simulated walk after the day fix)
    q = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    q.on("pageerror", lambda e: errors.append(f"drsim: {e}"))
    q.goto(BASE + "/?drsim=1"); q.wait_for_timeout(800); q.click("#mDay"); q.wait_for_timeout(600)
    q.select_option("#demoSel", opts[0]); q.click("#useDemo")
    q.wait_for_function("document.getElementById('big').textContent.includes('BRG')", timeout=120000)
    q.evaluate("window.drSim()"); q.wait_for_timeout(1500)
    q.locator("#res").screenshot(path=str(OUT / "phone_breadcrumb.png"))
    # HUD (glasses 600x600)
    h = b.new_page(viewport={"width": 600, "height": 600})
    h.on("pageerror", lambda e: errors.append(f"hud: {e}"))
    h.goto(BASE + "/?hud=1"); h.wait_for_timeout(2500)
    h.screenshot(path=str(OUT / "hud.png"))
    # demo gallery
    d = b.new_page(viewport={"width": 1366, "height": 900})
    d.on("pageerror", lambda e: errors.append(f"demo: {e}"))
    d.goto(BASE + "/demo"); d.wait_for_timeout(1500)
    for i in range(3):
        d.locator("#g_synthetic .b").nth(i).click()
    d.locator("#g_pixel .b").nth(0).click()
    d.locator("#g_ch1 .b").nth(0).click()
    d.wait_for_timeout(15000)
    d.evaluate("window.scrollTo(0,0)"); d.wait_for_timeout(500)
    d.screenshot(path=str(OUT / "demo.png"), full_page=False)
    d.screenshot(path=str(OUT / "demo_full.png"), full_page=True)
    b.close()
print("errors:", errors)
print(sorted(x.name for x in OUT.glob("*.png")))
