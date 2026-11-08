"""Tap Three detector.

Spectral-flux onset detection -> a "pattern" when exactly three onsets fall at a constant
interval (each gap within +-15% of the mean gap, mean gap 0.5-1.5 s) and no other comparable
onset sits in a guard window of 1.5 x gap before the first tap or after the third. A second
pattern with a similar gap within 10 s turns it into a "confirmed" event.

Works on any mono signal (contact mic WAV, phone audio, geophone) given its sample rate;
all window sizes are in seconds, not samples.

CLI:  python detect.py file.wav [--fs N] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict

import numpy as np
import scipy.signal as ss

# ---- parameters (seconds unless noted) --------------------------------------------------
WIN_S = 0.023          # STFT window
HOP_S = 0.005          # STFT hop -> 5 ms onset resolution
MIN_GAP_S = 0.12       # two onsets closer than this are one onset
THR_MED_S = 1.0        # adaptive threshold: running median over this span
THR_K = 6.0            # tap threshold = median + K * MAD of flux
THR_K_GUARD = 3.0      # lower threshold used only to look for intruders in the guard window
ABS_FLOOR = 1e-3       # flux floor so pure digital silence never triggers
INTERVAL_MIN, INTERVAL_MAX = 0.5, 1.5
TOL = 0.15             # each gap within +-15 % of the mean gap
GUARD_X = 1.5          # guard window = 1.5 x gap on both sides
GUARD_REL = 0.25       # onsets with peak amplitude < 25 % (-12 dB) of the weakest tap don't veto
AMP_RATIO_MAX = 6.0    # strongest/weakest tap strength must be below this
CONFIRM_WITHIN_S = 10.0
CONFIRM_GAP_TOL = 0.25


@dataclass
class Onset:
    t: float
    strength: float         # flux / tap threshold (detection)
    amp: float = 0.0        # peak |x| in the 60 ms after the onset (guard + consistency)


@dataclass
class Pattern:
    t_start: float
    t_end: float
    interval: float
    max_dev: float          # worst gap deviation as a fraction of the mean gap
    confidence: float
    taps: list
    strength: float = 0.0   # weakest tap's flux / threshold (signal strength proxy)


@dataclass
class Event:
    kind: str               # "pattern" or "confirmed"
    t: float                # time of the last tap of the (last) pattern, seconds from stream start
    t_start: float
    interval: float
    confidence: float
    n_patterns: int
    strength: float = 0.0


def spectral_flux(x: np.ndarray, fs: float) -> tuple[np.ndarray, float]:
    """Half-wave rectified log-magnitude spectral flux. Returns (flux, frame_rate)."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x - np.mean(x)
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak > 0:
        x = x / peak
    nwin = max(16, int(round(WIN_S * fs)))
    hop = max(1, int(round(HOP_S * fs)))
    if x.size < nwin + hop:
        return np.zeros(0), fs / hop
    _, _, Z = ss.stft(x, fs=fs, nperseg=nwin, noverlap=nwin - hop, boundary=None, padded=False)
    mag = np.log1p(100.0 * np.abs(Z))
    d = np.diff(mag, axis=1)
    flux = np.maximum(d, 0).mean(axis=0)
    flux = np.concatenate([[0.0], flux])
    return flux, fs / hop


def detect_onsets(x: np.ndarray, fs: float, k_mad: float = THR_K, flux_fr=None) -> list[Onset]:
    flux, fr = flux_fr if flux_fr is not None else spectral_flux(x, fs)
    if flux.size < 3:
        return []
    k = max(3, int(THR_MED_S * fr) | 1)
    med = ss.medfilt(flux, k) if flux.size >= k else np.full_like(flux, np.median(flux))
    mad = np.median(np.abs(flux - np.median(flux))) + 1e-9
    thr = np.maximum(med + k_mad * mad, ABS_FLOOR)
    peaks, _ = ss.find_peaks(flux, height=thr, distance=max(1, int(MIN_GAP_S * fr)))
    ref = np.maximum(med + THR_K * mad, ABS_FLOOR)   # strengths always relative to the tap threshold
    xa = None
    if x is not None:
        xa = np.abs(np.asarray(x, dtype=np.float64) - np.mean(x))
    out = []
    for p in peaks:
        t = float(p / fr)
        amp = 0.0
        if xa is not None:
            i0 = max(0, int((t - HOP_S) * fs)); i1 = min(xa.size, int((t + 0.06) * fs))
            amp = float(xa[i0:i1].max()) if i1 > i0 else 0.0
        out.append(Onset(t=t, strength=float(flux[p] / (ref[p] + 1e-12)), amp=amp))
    return out


def find_patterns(onsets: list[Onset], weak: list[Onset] | None = None) -> list[Pattern]:
    """Triples (a, b, c) of tap-threshold onsets, not necessarily adjacent: quieter onsets between
    or around them are allowed only if they are below the guard floor (-12 dB of the weakest tap)."""
    weak = onsets if weak is None else weak
    out: list[Pattern] = []
    n = len(onsets)
    seen = set()
    for i in range(n):
        a = onsets[i]
        for j in range(i + 1, n):
            b = onsets[j]
            g1 = b.t - a.t
            if g1 > INTERVAL_MAX * (1 + TOL):
                break
            if g1 < INTERVAL_MIN * (1 - TOL):
                continue
            for k in range(j + 1, n):
                c = onsets[k]
                g2 = c.t - b.t
                if g2 > g1 * (1 + 2 * TOL) + 1e-9:
                    break
                mean = (g1 + g2) / 2
                if not (INTERVAL_MIN <= mean <= INTERVAL_MAX):
                    continue
                dev = max(abs(g1 - mean), abs(g2 - mean)) / mean
                if dev > TOL:
                    continue
                amps = [a.amp, b.amp, c.amp]
                if max(amps) / max(min(amps), 1e-12) > AMP_RATIO_MAX:
                    continue
                floor = GUARD_REL * min(amps)
                lo, hi = a.t - GUARD_X * mean, c.t + GUARD_X * mean
                taps_t = (a.t, b.t, c.t)
                if any(lo < o.t < hi and o.amp >= floor and min(abs(o.t - tt) for tt in taps_t) > MIN_GAP_S / 2
                       for o in weak):
                    continue
                key = (round(a.t, 2), round(c.t, 2))
                if key in seen:
                    continue
                seen.add(key)
                s_ = [a.strength, b.strength, c.strength]
                timing = 1.0 - dev / TOL
                snr = min(1.0, np.log10(min(s_)) / np.log10(20.0)) if min(s_) > 1 else 0.0
                conf = round(float(0.5 + 0.3 * timing + 0.2 * snr), 3)
                out.append(Pattern(t_start=a.t, t_end=c.t, interval=round(mean, 4), max_dev=round(dev, 4),
                                   confidence=conf, taps=[round(a.t, 3), round(b.t, 3), round(c.t, 3)],
                                   strength=round(float(min(s_)), 2)))
    out.sort(key=lambda p: p.t_end)
    return out


def patterns_to_events(patterns: list[Pattern]) -> list[Event]:
    events: list[Event] = []
    used_as_confirm = set()
    for i, p in enumerate(patterns):
        events.append(Event("pattern", round(p.t_end, 3), round(p.t_start, 3), p.interval, p.confidence, 1, p.strength))
        for j in range(i - 1, -1, -1):
            q = patterns[j]
            if p.t_start - q.t_end > CONFIRM_WITHIN_S:
                break
            if j in used_as_confirm or q.t_end >= p.t_start:
                continue
            if abs(p.interval - q.interval) / q.interval <= CONFIRM_GAP_TOL:
                conf = round(1 - (1 - p.confidence) * (1 - q.confidence), 3)
                events.append(Event("confirmed", round(p.t_end, 3), round(q.t_start, 3),
                                    round((p.interval + q.interval) / 2, 4), conf, 2, min(p.strength, q.strength)))
                used_as_confirm.update({i, j})
                break
    return events


def detect(x: np.ndarray, fs: float) -> dict:
    ffr = spectral_flux(x, fs)
    onsets = detect_onsets(x, fs, THR_K, ffr)
    weak = detect_onsets(x, fs, THR_K_GUARD, ffr)
    patterns = find_patterns(onsets, weak)
    events = patterns_to_events(patterns)
    return {"onsets": [asdict(o) for o in onsets],
            "patterns": [asdict(p) for p in patterns],
            "events": [asdict(e) for e in events]}


def load_audio(path: str) -> tuple[np.ndarray, float]:
    import soundfile as sf
    x, fs = sf.read(path, always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x.astype(np.float64), float(fs)


def synth_taps(fs=16000, dur=10.0, tap_times=(1.0, 2.0, 3.0), noise=0.01, seed=0,
               f0=900.0, decay=0.02):
    """Synthetic knuckle taps: decaying sinusoid + click on white noise. For self-test only."""
    rng = np.random.default_rng(seed)
    x = noise * rng.standard_normal(int(dur * fs))
    n = int(0.15 * fs)
    tt = np.arange(n) / fs
    burst = np.sin(2 * np.pi * f0 * tt) * np.exp(-tt / decay)
    burst[:int(0.001 * fs)] += 1.0
    for t0 in tap_times:
        i = int(t0 * fs)
        x[i:i + n] += burst[:max(0, min(n, x.size - i))] * (0.8 + 0.4 * rng.random())
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", nargs="?")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        cases = {
            "two patterns (expect confirmed)": synth_taps(tap_times=(1, 2, 3, 6.5, 7.5, 8.5)),
            "one pattern (expect pattern only)": synth_taps(tap_times=(2, 3, 4)),
            "steady 6 beats (expect none)": synth_taps(tap_times=(1, 2, 3, 4, 5, 6)),
            "two taps (expect none)": synth_taps(tap_times=(2, 3)),
            "uneven (expect none)": synth_taps(tap_times=(1, 2, 3.5)),
            "noise only (expect none)": synth_taps(tap_times=()),
        }
        for name, x in cases.items():
            r = detect(x, 16000)
            kinds = [e["kind"] for e in r["events"]]
            print(f"{name:38s} onsets={len(r['onsets'])} events={kinds}")
        return
    if not a.wav:
        ap.error("wav path or --selftest")
    x, fs = load_audio(a.wav)
    r = detect(x, fs)
    if a.json:
        json.dump(r, sys.stdout, indent=1)
    else:
        for e in r["events"]:
            print(e)


if __name__ == "__main__":
    main()
