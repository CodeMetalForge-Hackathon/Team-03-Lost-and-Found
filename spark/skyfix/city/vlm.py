"""Optional landmark proposals from Qwen3-VL-4B (local transformers weights, ~/models/qwen3-vl-4b).

Loads in a background thread at server start (it took 47–51 s on this Spark earlier tonight). Until it is ready the page
says so and the user taps everything by hand. Proposals are only suggestions: the user confirms or corrects every one.
The model is asked for visible landmarks from a closed list with a point in Qwen3-VL's 0–1000 relative coordinates.
"""
import json, re, threading, time
from pathlib import Path

MODEL = Path.home() / "models/qwen3-vl-4b"
S = {"status": "not started", "model": None, "proc": None, "load_s": None, "error": None}
LOCK = threading.Lock()


def _load():
    S["status"] = "loading"; t0 = time.time()
    try:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        S["model"] = Qwen3VLForConditionalGeneration.from_pretrained(str(MODEL), dtype=torch.bfloat16, device_map="cuda")
        S["proc"] = AutoProcessor.from_pretrained(str(MODEL))
        S["load_s"] = round(time.time() - t0, 1); S["status"] = "ready"
    except Exception as e:
        S["status"] = "failed"; S["error"] = f"{type(e).__name__}: {e}"[:300]


def start():
    if S["status"] == "not started" and MODEL.exists():
        threading.Thread(target=_load, daemon=True).start()
    elif not MODEL.exists():
        S["status"] = "failed"; S["error"] = f"no weights at {MODEL}"


def propose(img, names, max_side=1280):
    """img: PIL RGB. names: candidate landmark names. Returns [{name, x, y}] in img pixel coords."""
    if S["status"] != "ready":
        return {"status": S["status"], "error": S["error"], "proposals": []}
    import torch
    im = img.copy(); im.thumbnail((max_side, max_side))
    prompt = ("This photo was taken from a high floor in downtown Boston. Which of these landmarks are clearly visible? "
              "Candidates: " + "; ".join(names) + ". "
              "Answer ONLY a JSON list like [{\"name\": \"<exact candidate name>\", \"point\": [x, y]}] where point marks the TOP of "
              "the landmark in coordinates from 0 to 1000 relative to image width and height. Omit anything you are not sure about.")
    msgs = [{"role": "user", "content": [{"type": "image", "image": im}, {"type": "text", "text": prompt}]}]
    t0 = time.time()
    with LOCK, torch.no_grad():
        inp = S["proc"].apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt").to("cuda")
        out = S["model"].generate(**inp, max_new_tokens=400, do_sample=False)
        txt = S["proc"].batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]
    m = re.search(r"\[.*\]", txt, re.S); props = []
    try:
        for p in json.loads(m.group(0)) if m else []:
            n = p.get("name"); pt = p.get("point") or p.get("point_2d")
            if n in names and pt and len(pt) == 2:
                props.append({"name": n, "x": pt[0] / 1000 * img.width, "y": pt[1] / 1000 * img.height})
    except Exception:
        pass
    return {"status": "ready", "proposals": props, "raw": txt[:600], "infer_s": round(time.time() - t0, 1),
            "note": "VLM suggestion only; confirm or correct each by tapping"}
