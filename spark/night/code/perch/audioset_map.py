"""AudioSet label -> HV (human vocal) / HNV (human non-vocal) / NH (not human), by keyword. Export with --export."""
from __future__ import annotations
import json, sys

HV_KEYS = ["speech", "shout", "yell", "scream", "crying", "baby cry", "sobbing", "whimper", "wail", "moan", "groan", "child singing",
           "bellow", "battle cry", "children shouting", "conversation", "narration", "babbling", "whispering", "singing", "humming", "grunt", "laughter", "baby laughter", "giggle", "chuckle", "sigh", "gasp", "pant"]
HNV_KEYS = ["clapping", "applause", "knock", "tap", "footsteps", "walk, footsteps", "run", "shuffle", "cough", "sneeze", "breathing", "wheeze", "snoring", "throat clearing", "sniff", "finger snapping", "hands", "slap", "smack", "whistling", "stomach rumble", "heart"]
# keyword false friends: these contain an HV/HNV keyword but are not human sounds.
NH_EXACT = {"whimper (dog)", "engine knocking", "heart murmur", "tapping (guitar technique)", "tap dance", "whistle", "steam whistle", "synthetic singing", "singing bowl", "speech synthesizer", "heart sounds, heartbeat", "dishes, pots, and pans", "trickle, dribble", "drum", "snare drum", "tabla", "wood block"}

def classify_label(name: str) -> str:
    n = name.strip().lower()
    if n in NH_EXACT:
        return "NH"
    if any(k in n for k in HV_KEYS):
        return "HV"
    if any(k == n or k in [p.strip() for p in n.replace(",", " ,").split(",")] or (len(k) > 4 and k in n) for k in HNV_KEYS):
        return "HNV"
    return "NH"

def build_map(labels: list[str]) -> dict[str, str]:
    return {l: classify_label(l) for l in labels}

if __name__ == "__main__":
    from panns_inference import labels
    m = build_map(list(labels))
    json.dump(m, open(sys.argv[2] if len(sys.argv) > 2 else "rb/audioset_map.json", "w"), indent=0)
    print({k: sum(v == k for v in m.values()) for k in ("HV", "HNV", "NH")})
    print("HV", [l for l, v in m.items() if v == "HV"])
    print("HNV", [l for l, v in m.items() if v == "HNV"])
