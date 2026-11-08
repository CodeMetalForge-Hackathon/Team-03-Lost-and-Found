"""Soak: 2 concurrent clients cycle all demo items for N minutes against :8130; log failures/latency/server RSS."""
import json, random, sys, threading, time, requests, pathlib
BASE = "http://127.0.0.1:8130"; MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 20
ids = [x["id"] for x in requests.get(BASE + "/api/demo_items").json()]
pid = int(pathlib.Path(__file__).resolve().parent.joinpath("run/app_http.pid").read_text())
stats = dict(n=0, fail=0, lat=[], errors=[]); lock = threading.Lock(); t_end = time.time() + MIN * 60
def rss():
    for l in open(f"/proc/{pid}/status"):
        if l.startswith("VmRSS"): return int(l.split()[1]) // 1024
def worker(seed):
    rnd = random.Random(seed)
    while time.time() < t_end:
        i = rnd.choice(ids); t = time.time()
        try:
            r = requests.post(BASE + "/api/solve", data={"demo_id": i}, timeout=180); ok = r.status_code == 200
            if ok: requests.get(BASE + "/api/last", timeout=10); requests.get(BASE + "/api/thumb/" + i, timeout=30)
        except Exception as e: ok = False; r = e
        with lock:
            stats["n"] += 1; stats["lat"].append(time.time() - t)
            if not ok: stats["fail"] += 1; stats["errors"].append(f"{i}: {str(getattr(r,'status_code',r))[:80]}")
ths = [threading.Thread(target=worker, args=(s,)) for s in (1, 2)]; [t.start() for t in ths]
log = open("logs/soak.jsonl", "a")
while any(t.is_alive() for t in ths):
    time.sleep(60)
    with lock:
        L = sorted(stats["lat"]) or [0]
        rec = dict(t=time.strftime("%H:%M"), n=stats["n"], fail=stats["fail"], p50=round(L[len(L)//2], 2), max=round(L[-1], 2), rss_mb=rss(), errors=stats["errors"][-3:])
    log.write(json.dumps(rec) + "\n"); log.flush()
ev = requests.get(BASE + "/api/evidence?n=1").json()["verify"]
log.write(json.dumps(dict(final=True, n=stats["n"], fail=stats["fail"], evidence_verify=ev)) + "\n")
