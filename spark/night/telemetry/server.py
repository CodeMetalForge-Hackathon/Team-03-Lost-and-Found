"""Runs Local — DGX Spark GB10 telemetry page on :8160. Stdlib + psutil (already in the venv). Read-only: probes, never changes."""
import glob, ipaddress, json, os, shutil, socket, ssl, subprocess, sys, threading, time, urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import psutil

HERE = Path(__file__).resolve().parent
HOME = Path.home()
N = 60
LOCAL_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "100.64.0.0/10", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")]
SERVICES = [("Sky Fix API", "http://127.0.0.1:8130/api/health"), ("Sky Fix PWA", "https://127.0.0.1:8131/"),
            ("Sky Fix City / Course", "https://127.0.0.1:8133/"), ("Trace Fusion shell", "http://127.0.0.1:8140/"),
            ("Dog replay + Dog's eye", "http://127.0.0.1:8141/"), ("Perch and Listen", "http://127.0.0.1:8142/"),
            ("Search Map / COP", "http://127.0.0.1:8143/"), ("Zoom AIR / WATER", "http://127.0.0.1:8150/air")]
MODELS = [("Qwen3-8B", [f"{HOME}/models/Qwen3-8B", f"{HOME}/.cache/huggingface/hub/models--Qwen--Qwen3-8B"]),
          ("Qwen3-VL-8B-Instruct", [f"{HOME}/models/qwen3-vl-8b-instruct"]),
          ("AerialPerson-YOLO26l", [f"{HOME}/forge/zoom/air/weights/aerialperson/AerialPerson-YOLO26*.pt"]),
          ("UATD YOLO11n best.pt (sonar)", [f"{HOME}/forge/zoom/water/uatd_yolo11n_best.pt"]),
          ("PANNs CNN14", [f"{HOME}/panns_data/Cnn14*.pth", f"{HOME}/forge/**/Cnn14*.pth", f"{HOME}/models/**/Cnn14*.pth"]),
          ("tetra3 star database (phone FOV)", [f"{HOME}/forge/skyfix/**/*phone*.npz", f"{HOME}/forge/skyfix/**/tetra3*/**/*.npz"]),
          ("Depth-Anything-V2-Small", [f"{HOME}/models/Depth-Anything-V2-Small-hf"])]
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

H = {k: deque(maxlen=N) for k in ("util", "mem", "power", "temp", "cpu")}
SH = {name: deque(maxlen=N) for name, _ in SERVICES}
STATE = {}


def size(p):
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink()) + \
        sum(f.resolve().stat().st_size for f in p.rglob("*") if f.is_symlink() and f.resolve().is_file())


def scan_models():
    out = []
    for name, pats in MODELS:
        hit = None
        for pat in pats:
            g = sorted(glob.glob(pat, recursive=True))
            if g:
                hit = g[0]; break
        out.append({"name": name, "path": hit.replace(str(HOME), "~") if hit else None,
                    "bytes": size(hit) if hit else 0})
    return out


def gpu():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        v = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        f = lambda s: None if s.startswith("[") or s in ("", "N/A") else float(s)  # noqa: E731
        return {"ok": True, "util": f(v[0]), "mem_used": f(v[1]), "mem_total": f(v[2]), "power": f(v[3]), "temp": f(v[4]), "raw": v}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def outbound():
    r = subprocess.run(["ss", "-tnH", "state", "established"], capture_output=True, text=True, timeout=5).stdout
    ext = []
    for line in r.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        peer = parts[-1].rsplit(":", 1)[0].strip("[]")
        try:
            ip = ipaddress.ip_address(peer.split("%")[0])
        except ValueError:
            continue
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.version == 6:
            if ip.is_loopback or ip.is_link_local or ip.is_private:   # fd7a:… tailscale ULA, fe80::, ::1
                continue
        elif any(ip in n for n in LOCAL_NETS):
            continue
        ext.append(parts[-1])
    return ext


def probe(url):
    t = time.time()
    try:
        r = urllib.request.urlopen(url, timeout=2, context=CTX if url.startswith("https") else None)
        code = r.status; r.read(256)
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return {"code": None, "ms": None, "error": type(e).__name__}
    return {"code": code, "ms": round((time.time() - t) * 1000, 1)}


def loop():
    psutil.cpu_percent(None)
    while True:
        g = gpu(); vm = psutil.virtual_memory(); du = shutil.disk_usage(HOME / "forge")
        cpu = psutil.cpu_percent(None)
        if g["ok"]:
            for k, gk in (("util", "util"), ("mem", "mem_used"), ("power", "power"), ("temp", "temp")):
                H[k].append(g[gk])
        H["cpu"].append(cpu)
        res = []
        ths = []
        out = [None] * len(SERVICES)

        def run(i, u):
            out[i] = probe(u)
        for i, (_, u) in enumerate(SERVICES):
            th = threading.Thread(target=run, args=(i, u)); th.start(); ths.append(th)
        for th in ths:
            th.join()
        for (name, u), p in zip(SERVICES, out):
            SH[name].append(p["ms"] if p["code"] and p["code"] < 400 else None)
            res.append({"name": name, "port": int(u.split(":")[2].split("/")[0]), "url": u.replace("127.0.0.1", "<spark>"), **p,
                        "hist": list(SH[name])})
        try:
            ext = outbound()
        except Exception as e:
            ext = [f"ss failed: {e}"]
        STATE.update(t=time.time(), gpu=g, hist={k: list(v) for k, v in H.items()}, cpu=cpu,
                     ram={"used": vm.total - vm.available, "total": vm.total},
                     disk={"used": du.used, "total": du.total, "path": "~/forge"}, services=res, outbound=ext,
                     uptime_s=time.time() - psutil.boot_time(), host=socket.gethostname())
        time.sleep(max(0.2, 2.0 - (time.time() - STATE["t"])))


class Hd(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(200); self.send_header("content-type", ctype); self.send_header("content-length", str(len(b)))
        self.send_header("cache-control", "no-store"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/metrics"):
            self.send(json.dumps({**STATE, "models": MODELS_FOUND}), "application/json")
        elif self.path in ("/", "/index.html"):
            self.send((HERE / "index.html").read_text(), "text/html; charset=utf-8")
        elif self.path == "/health":
            self.send('{"ok":true}', "application/json")
        else:
            self.send_error(404)


MODELS_FOUND = scan_models()
if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8160
    ThreadingHTTPServer(("0.0.0.0", port), Hd).serve_forever()
