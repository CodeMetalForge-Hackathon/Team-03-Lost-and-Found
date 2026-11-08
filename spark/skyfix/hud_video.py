"""10-second HUD video for the pitch deck: phone solves a demo fix, glasses HUD (600x600) follows with a simulated
compass sweep. Output: screenshots/hud_10s.webm (+ .mp4 if ffmpeg exists)."""
import pathlib, shutil, subprocess, time, requests
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8130"; OUT = pathlib.Path(__file__).resolve().parent / "screenshots"
requests.post(BASE + "/api/solve", data={"demo_id": "synth:boston_az150_alt35"}, timeout=120)
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 600, "height": 600}, record_video_dir=str(OUT / "_vid"), record_video_size={"width": 600, "height": 600})
    pg = ctx.new_page(); pg.goto(BASE + "/?hud=1&sim=1"); pg.wait_for_timeout(10000)
    vp = pg.video.path(); ctx.close(); b.close()
dst = OUT / "hud_10s.webm"; shutil.move(vp, dst); shutil.rmtree(OUT / "_vid", ignore_errors=True)
if shutil.which("ffmpeg"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(dst), "-pix_fmt", "yuv420p", str(dst.with_suffix(".mp4"))])
print(dst, dst.stat().st_size)
