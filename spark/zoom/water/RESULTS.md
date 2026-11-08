# WATER — UATD forward-looking-sonar detector (YOLO11n)

**Data.** UATD (Xie et al., 2022; figshare 21331143, CC BY 4.0): multibeam forward-looking sonar (Tritech Gemini 1200ik), 10 target classes including `human body` (a dummy), PASCAL-VOC XML. Raw frames are polar: 1024 beams × 1950 range bins, 120° azimuth, range from the XML (~5–20 m).
Split: **train** = UATD_Training (7600 frames), **val** = UATD_Test_1 (800, used to pick best.pt), **test** = UATD_Test_2 (800, held out: not used for training or checkpoint selection).

**Training.** YOLO11n (COCO-pretrained), 640 px, 30 epochs, batch 32, seed 0, ultralytics 8.4.204 in `~/forge/.venv`. Wall clock **21.1 min** on the GB10 (the 60-min box was not reached). Weights: `water/uatd_yolo11n_best.pt`.
Re-run: `~/forge/.venv/bin/python water/scripts/uatd_to_yolo.py water/uatd water/yolo && ~/forge/.venv/bin/python water/scripts/train_uatd.py water/yolo/data.yaml water/runs`; evaluation numbers come from `model.val(split=...)`, saved in `water/uatd_results.json`.

| | val (Test_1) | **test (Test_2, held out)** |
|---|---|---|
| mAP50 | 0.839 | **0.817** |
| mAP50-95 | 0.351 | 0.350 |
| precision / recall | 0.886 / 0.794 | 0.798 / 0.818 |
| **human body AP50** | 0.877 | **0.910** |

Per class (AP50):

| class | train boxes | test boxes | val AP50 | test AP50 |
|---|---|---|---|---|
| cube | 2645 | 168 | 0.758 | 0.729 |
| ball | 3072 | 193 | 0.865 | 0.880 |
| cylinder | 564 | 45 | 0.965 | 0.935 |
| human body | 1283 | 73 | 0.877 | 0.910 |
| tyre | 1124 | 121 | 0.813 | 0.807 |
| circle cage | 661 | 99 | 0.530 | 0.552 |
| square cage | 980 | 168 | 0.622 | 0.557 |
| metal bucket | 476 | 5 | 0.995 | 0.846 |
| plane | 795 | 135 | 0.987 | 0.991 |
| rov | 700 | 150 | 0.982 | 0.958 |

**Limits (say these out loud).**
- The `human body` class is a submerged **dummy** in UATD's test environments, not a drowned person. 73 test instances.
- Test_1/Test_2 come from the same collection campaign and sonar as training, so this is an in-distribution score, not cross-site. A different sonar, water body or seabed clutter will score lower.
- 640 px input shrinks the 1024×1950 polar frame ~3×; small targets lose detail. No tuning was done beyond the prompt's settings.
