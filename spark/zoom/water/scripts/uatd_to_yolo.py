"""UATD (PASCAL-VOC XML) -> YOLO detection dataset.

Usage: uatd_to_yolo.py <uatd_root> <out_dir>
Finds every .xml under uatd_root, pairs it with the image of the same stem, and
splits by the folder it came from (Training / Validation / Test words in the path).
Writes out_dir/{images,labels}/{train,val,test} (images symlinked) and data.yaml.
"""
import sys, os, re, json, collections
import xml.etree.ElementTree as ET
from pathlib import Path

# UATD's 10 classes (Xie et al. 2022). 'human body' kept as its own class.
CANON = ["cube", "ball", "cylinder", "human body", "tyre", "circle cage",
         "square cage", "metal bucket", "plane", "rov"]


def norm(name):
    n = name.strip().lower().replace("_", " ")
    n = re.sub(r"\s+", " ", n)
    alias = {"humanbody": "human body", "tire": "tyre", "circlecage": "circle cage",
             "squarecage": "square cage", "metalbucket": "metal bucket"}
    return alias.get(n.replace(" ", ""), n)


def split_of(p):
    # UATD ships Training / Test_1 / Test_2 (stems repeat across sets). Test_1 = val (best.pt selection),
    # Test_2 = held-out test, never seen during training or checkpoint selection.
    s = str(p).lower()
    if "test_2" in s:
        return "test"
    if "test_1" in s or "val" in s:
        return "val"
    return "train"


def main(root, out):
    root, out = Path(root), Path(out)
    imgs = {}
    for ext in ("*.bmp", "*.png", "*.jpg", "*.jpeg"):
        for p in root.rglob(ext):
            imgs.setdefault((split_of(p), p.stem), p)
    xmls = sorted(root.rglob("*.xml"))
    counts = collections.Counter()
    per_split = collections.Counter()
    unknown = collections.Counter()
    missing = 0
    for x in xmls:
        sp = split_of(x)
        img = imgs.get((sp, x.stem))
        if img is None:
            missing += 1
            continue
        t = ET.parse(x).getroot()
        size = t.find("size")
        W, H = float(size.find("width").text), float(size.find("height").text)
        lines = []
        for o in t.findall("object"):
            c = norm(o.find("name").text)
            if c not in CANON:
                unknown[c] += 1
                continue
            b = o.find("bndbox")
            x0, y0, x1, y1 = (float(b.find(k).text) for k in ("xmin", "ymin", "xmax", "ymax"))
            x0, x1 = max(0, min(x0, x1)), min(W, max(x0, x1))
            y0, y1 = max(0, min(y0, y1)), min(H, max(y0, y1))
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            lines.append(f"{CANON.index(c)} {(x0+x1)/2/W:.6f} {(y0+y1)/2/H:.6f} {(x1-x0)/W:.6f} {(y1-y0)/H:.6f}")
            counts[(sp, c)] += 1
        (out / "images" / sp).mkdir(parents=True, exist_ok=True)
        (out / "labels" / sp).mkdir(parents=True, exist_ok=True)
        dst = out / "images" / sp / img.name
        if not dst.exists():
            os.symlink(img.resolve(), dst)
        (out / "labels" / sp / (img.stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
        per_split[sp] += 1
    has_val = per_split.get("val", 0) > 0
    yaml = [f"path: {out.resolve()}", "train: images/train",
            f"val: images/{'val' if has_val else 'test'}", "test: images/test", "names:"]
    yaml += [f"  {i}: {n}" for i, n in enumerate(CANON)]
    (out / "data.yaml").write_text("\n".join(yaml) + "\n")
    summary = {"xml": len(xmls), "images_per_split": dict(per_split), "xml_without_image": missing,
               "unknown_classes": dict(unknown),
               "boxes": {f"{s}/{c}": n for (s, c), n in sorted(counts.items())}}
    (out / "convert_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
