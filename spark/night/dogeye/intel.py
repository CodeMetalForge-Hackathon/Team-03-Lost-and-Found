"""Open model on top of the reconstruction: Qwen3 text debrief + Qwen3-VL reading of the renders.

Order: vLLM :8001 (text) / :8002 (VL) if up → local transformers (Qwen/Qwen3-8B, Qwen/Qwen3-VL-8B-Instruct, cached)
if it loads in < 5 min → else skip and say so. Writes OUT_DIR/intel.md and intel.json.
Usage: intel.py OUT_DIR
"""
from __future__ import annotations
import json, sys, time, urllib.request, base64, re
from pathlib import Path

OUT = Path(sys.argv[1])
TEXT_ID, VL_ID = "Qwen/Qwen3-8B", "Qwen/Qwen3-VL-8B-Instruct"
if Path("/home/darkstar90/models/qwen3-vl-8b-instruct/config.json").exists():   # HF cache copy has no weights
    VL_ID = "/home/darkstar90/models/qwen3-vl-8b-instruct"
VL_ONLY = "--vl-only" in sys.argv and (OUT / "intel.json").exists()
LOAD_BUDGET_S = 300

meta = json.loads((OUT / "legs.json").read_text())
track = (OUT / "track.csv").read_text()
legs_compact = [{k: l[k] for k in ("leg", "start", "end", "kind", "d_min", "d_max", "mean_speed_cm_s", "still_frac",
                                     "mean_activity", "events", "note")} for l in meta["legs"]]

SYSTEM = ("You are a search-and-rescue K9 data analyst. You only state what the data shows. "
          "Every line you write must cite at least one time in seconds and, when relevant, a range in cm, copied from the data. "
          "Never invent sensors: the pack has one forward ultrasonic ranger (15° beam, 1 Hz), a 3-axis accelerometer "
          "(activity, MOVING if > 6, TILT alerts), a sound sensor (BARK alerts = loud sound), a DHT11 (temp_c, humidity) and a "
          "contact thermistor (therm_c, NOT infrared). There is no heading, odometry, GPS or camera.")
USER = f"""Run: {meta['run']} ({meta['duration_s']:.0f} s, {meta['n_heartbeats']} heartbeats at 1 Hz).
Method: {meta['method']}.

LEGS (from reconstruct.py):
{json.dumps(legs_compact, indent=0)}

ALERTS: {json.dumps(meta['alerts'])}

TRACK (t s, d_cm, x_along_m, heading_id, leg, state, activity, temp_c, humidity, therm_c, ...):
{chr(10).join(l for l in track.splitlines()[:60])}

Write EXACTLY this, nothing else:
DEBRIEF
1. ... (10 numbered plain-English lines describing what the dog did, in time order; each line cites times in s and ranges in cm from the data)
FLAGS
A. Gait-tilt false alerts: (count TILT alerts while MOVING, cite their times, explain they are gait bob, not sitting/falling)
B. Single loud sound at arrival: (cite the BARK time and the range at that moment; say it coincides with arrival/back-off and is likely servos or the handler, not a confirmed bark)
C. Echo loss = open floor: (cite the time the echo was lost and the last range before it; say this is open floor beyond the beam, not a sensor fault)"""


def vllm(port, payload, timeout=240):
    req = urllib.request.Request(f"http://localhost:{port}/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())["choices"][0]["message"]["content"]


def up(port):
    try:
        return json.loads(urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2).read())["data"][0]["id"]
    except Exception:
        return None


def strip_think(s):
    return re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()


log = {"t_start": time.strftime("%H:%M:%S")}
text_out = vl_out = None
# ---------------- text ----------------
m = up(8001)
if VL_ONLY:
    prev = json.loads((OUT / "intel.json").read_text())
    text_out = prev["text"]; log.update({k: v for k, v in prev["log"].items() if k.startswith("text")})
elif m:
    log["text_backend"] = f"vLLM :8001 ({m})"
    text_out = strip_think(vllm(8001, {"model": m, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER + " /no_think"}],
                                       "temperature": 0.2, "max_tokens": 1200}))
else:
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        t0 = time.time()
        tok = AutoTokenizer.from_pretrained(TEXT_ID)
        model = AutoModelForCausalLM.from_pretrained(TEXT_ID, dtype=torch.bfloat16, device_map="cuda")
        lt = time.time() - t0
        log["text_load_s"] = round(lt, 1)
        if lt > LOAD_BUDGET_S:
            raise RuntimeError(f"load took {lt:.0f} s > {LOAD_BUDGET_S} s budget")
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
        prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False, tokenize=False)
        enc = tok(prompt, return_tensors="pt").to("cuda")
        t1 = time.time()
        with torch.no_grad():
            o = model.generate(**enc, max_new_tokens=1200, do_sample=False)
        text_out = strip_think(tok.decode(o[0, enc["input_ids"].shape[1]:], skip_special_tokens=True))
        log["text_backend"] = f"transformers {TEXT_ID} bf16 (greedy, thinking off)"; log["text_gen_s"] = round(time.time() - t1, 1)
        del model; torch.cuda.empty_cache()
    except Exception as e:
        import traceback; traceback.print_exc()
        log["text_backend"] = f"SKIPPED: {type(e).__name__}: {e}"
print("text:", log.get("text_backend"), flush=True)

# ---------------- vision ----------------
VL_PROMPT = ("These are renders of a reconstruction computed from a single forward ultrasonic range sensor on a small quadruped. "
             "Image 1 is top-down (orange = estimated track, gold bars = surfaces the sensor detected, blue = area swept by its beam). "
             "Image 2 is a first-person render from the sensor at 0.12 m height at two moments. "
             "Describe the geometry you see: how many surfaces, their arrangement relative to each other, approximate distances "
             "using the axis labels, and the path. Then say in one sentence what this geometry cannot tell you. 8 sentences max.")
imgs = [OUT / "topdown.png", OUT / "dogseye.png"]
m = up(8002)
if m:
    log["vl_backend"] = f"vLLM :8002 ({m})"
    content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()}} for p in imgs]
    vl_out = strip_think(vllm(8002, {"model": m, "messages": [{"role": "user", "content": content + [{"type": "text", "text": VL_PROMPT}]}],
                                     "temperature": 0.2, "max_tokens": 600}))
else:
    try:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        t0 = time.time()
        proc = AutoProcessor.from_pretrained(VL_ID)
        vlm = Qwen3VLForConditionalGeneration.from_pretrained(VL_ID, dtype=torch.bfloat16, device_map="cuda")
        lt = time.time() - t0; log["vl_load_s"] = round(lt, 1)
        if lt > LOAD_BUDGET_S:
            raise RuntimeError(f"load took {lt:.0f} s > {LOAD_BUDGET_S} s budget")
        msgs = [{"role": "user", "content": [{"type": "image", "image": str(p)} for p in imgs] + [{"type": "text", "text": VL_PROMPT}]}]
        inp = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt").to("cuda")
        t1 = time.time()
        with torch.no_grad():
            o = vlm.generate(**inp, max_new_tokens=600, do_sample=False)
        vl_out = strip_think(proc.batch_decode(o[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0])
        log["vl_backend"] = f"transformers {VL_ID} bf16 (greedy)"; log["vl_gen_s"] = round(time.time() - t1, 1)
    except Exception as e:
        import traceback; traceback.print_exc()
        log["vl_backend"] = f"SKIPPED: {type(e).__name__}: {e}"
print("vl:", log.get("vl_backend"), flush=True)

def factcheck():
    """Ground truth for the three flags, computed from track.csv / alerts by code (not by the model)."""
    import csv
    R = list(csv.DictReader(open(OUT / "track.csv")))
    tt = [float(r["t"]) for r in R]
    near = lambda t: R[min(range(len(R)), key=lambda k: abs(tt[k] - t))]
    tilts = [a for a in meta["alerts"] if a["kind"] == "TILT"]
    mv = [a for a in tilts if near(a["t"])["state"] == "MOVING"]
    barks = [a for a in meta["alerts"] if a["kind"] == "BARK"]
    lost = next((k for k in range(1, len(R)) if R[k]["d_cm"] == "" and R[k - 1]["d_cm"] != ""), None)
    rows = [f"| A. TILT alerts while MOVING | {len(mv)} of {len(tilts)} TILT alerts: " + ", ".join(f'{a["t"]:.1f}' for a in mv) + " s |"]
    for b in barks:
        pre = max((r for r in R if float(r["t"]) <= b["t"] and r["d_cm"]), key=lambda r: float(r["t"]), default=None)
        post = min((r for r in R if float(r["t"]) > b["t"] and r["d_cm"]), key=lambda r: float(r["t"]), default=None)
        rows.append(f"| B. BARK | {b['t']:.2f} s; range {pre['d_cm'] if pre else '?'} cm at {pre['t'] if pre else '?'} s → "
                    f"{post['d_cm'] if post else '?'} cm at {post['t'] if post else '?'} s (backing off from the 14–15 cm arrival at 21–23 s) |")
    if lost is not None:
        rows.append(f"| C. echo lost | first blank at {R[lost]['t']} s; last range {R[lost - 1]['d_cm']} cm at {R[lost - 1]['t']} s |")
    return ["## Fact check (computed by code from track.csv, not by the model)", "", "| flag | data |", "|---|---|"] + rows + [""]


md = [f"# Model debrief: {meta['run']}", "",
      f"Text model: {log.get('text_backend')}. Vision model: {log.get('vl_backend')}.",
      "The input was legs.json + track.csv + the alert list from reconstruct.py. Output is shown verbatim below; check the times against legs.json before quoting it.", "",
      "## Debrief (Qwen3, from the data)", "", text_out or "_skipped; see backend line above_", "",
      "## Geometry reading (Qwen3-VL)", "",
      "> **Model reading of a rendered reconstruction, not of the room.** Room-prior headings are not measured.", "",
      vl_out or "_skipped; see backend line above_", ""] + factcheck()
(OUT / "intel.md").write_text("\n".join(md))
log["t_end"] = time.strftime("%H:%M:%S")
(OUT / "intel.json").write_text(json.dumps(dict(log=log, text=text_out, vl=vl_out), indent=1))
print(json.dumps(log, indent=1))
