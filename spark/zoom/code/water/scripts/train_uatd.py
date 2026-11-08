"""Train YOLO11n on UATD (YOLO format). 640 px, 30 epochs, batch 32, hard 60-min wall-clock box.

Usage: ~/forge/.venv/bin/python train_uatd.py <data.yaml> <project_dir>
The time box is enforced by a callback that sets trainer.stop after the epoch that crosses
60 min, so the run ends cleanly and best.pt / last.pt are written (no extension of epochs).
"""
import sys, time
from ultralytics import YOLO

BOX_S = 60 * 60
data, project = sys.argv[1], sys.argv[2]
t0 = time.time()


def box(trainer):
    el = time.time() - t0
    print(f"[timebox] epoch {trainer.epoch + 1} done at {el/60:.1f} min", flush=True)
    if el > BOX_S - 60:
        print("[timebox] 60-min box reached; stopping after this epoch", flush=True)
        trainer.stop = True


m = YOLO("yolo11n.pt")
m.add_callback("on_fit_epoch_end", box)
m.train(data=data, imgsz=640, epochs=30, batch=32, project=project, name="yolo11n_uatd",
        exist_ok=True, workers=8, seed=0, deterministic=False, plots=True, patience=100)
print(f"[timebox] total {(time.time()-t0)/60:.1f} min", flush=True)
