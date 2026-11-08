# LAND — zero-shot dog vocalisation tagging (PANNs, AST)

**Data.** Dog play pant (Zenodo 18972388, CC BY 4.0; BARKS Lab, ELTE Budapest): 30 annotated dog–human play sessions, 17 young dogs, 48 kHz. Expert-reviewed (SecondLayer) labels: Pant 1294, Human 581, Other 264, Growl 198, Grunt 163, Bark/yelp 48, Moan 33, Sneeze 25, Whine 13, Cough/woof 10, Shake 7. Only the 0.38 GB session-audio archive was fetched (the 43 GB raw-video archive was still downloading and is not needed).
**Method.** No training. Every labelled segment is cut as a window centred on the call (max(1 s, call length), ≤ 4 s) and scored by PANNs CNN14 and AST (AudioSet). Bark score = max(Bark, Yip, Bow-wow). Re-run: `~/forge/.venv/bin/python land/eval_dog.py` (writes `land/results.json`).

| model | **bark vs all other segments: AUC** | P / R at 0.3 | P / R at 0.5 | dog vs human AUC | 4-way call type top-1 | recall bark / whine / growl / pant |
|---|---|---|---|---|---|---|
| panns-cnn14 | 0.988 | 0.43 / 0.98 | 0.61 / 0.75 | 0.70 | 0.49 | 0.98 / 0.46 / 0.47 / 0.47 |
| ast-audioset | 0.984 | 0.57 / 0.90 | 0.50 / 0.06 | 0.64 | 0.33 | 0.98 / 0.61 / 0.56 / 0.27 |

48 barks, 2588 other segments (pants, growls, grunts, human speech, …). 4-way call type uses only Bark/yelp, Whine, Growl, Pant (1553 segments, 83 % pants).

**What it means.** Barks are found reliably by both models (AUC ≈ 0.99). Whines (13 examples), growls and especially pants are not: pants are quiet breathing that AudioSet models mostly call something else, so "is a dog present" from audio alone is weak (AUC 0.64–0.70). **Howl cannot be validated: the dataset has no howl label.**

**Wiring.** `land/bark_live.py` runs PANNs on 1 s windows (hop 0.5 s, threshold 0.5, 2 s refractory) from a mic (`--mic`, none is attached to the Spark tonight) or a replay (`--wav`), and drops `kind=dog_bark` events into `night/inbox` at the dog stand-in's floor position at that moment. The modality weight for dog_bark was lowered to **0.3** in `night/config.json` (low weight). On the P-03 session replay the 19 events line up with the expert bark annotations (e.g. 53.8, 55.4, 74.7, 82.5 … 134.0 s). Every replay event says REPLAY and, while only the synthetic dog run exists, that its position is SYNTHETIC.
**Limits.** Indoor lab recordings of young dogs at play, close microphones; a field dog at distance in wind is harder. The evaluation set includes the replay session (no training is involved, so there is no leakage, but it is not a field test).
