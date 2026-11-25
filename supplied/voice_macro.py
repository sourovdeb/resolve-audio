#!/usr/bin/env python3
"""
voice_macro.py - reference DSP for a 3-knob voice enhancer ("Voice Macro").

Knobs (all 0..1, 0 = that stage is off):
  depth     -> low-end body bell + mud cut   (warmth / "deeper voice")
  presence  -> presence bell + air shelf + de-esser   (clarity, kept tame)
  control   -> expander + compressor + auto makeup    (even, "radio" level)

Chain: HPF -> expander -> EQ -> de-esser -> compressor(+makeup) -> limiter

This is a PROTOTYPE of the math. It runs offline on a numpy array.
The same maths is what a VST3 (JUCE) or a hand-built Fairlight preset implements.
"""
import sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

EPS = 1e-12


def db2lin(db):
    return 10.0 ** (np.asarray(db) / 20.0)


def lin2db(x):
    return 20.0 * np.log10(np.maximum(np.abs(x), EPS))


# ----------------------------------------------------------------------------
# 1) KNOB -> PARAMETER MAP  (this is the "logic" - edit the numbers here)
# ----------------------------------------------------------------------------
def map_knobs(depth, presence, control, fs=48000):
    d, p, c = (float(np.clip(v, 0.0, 1.0)) for v in (depth, presence, control))
    return dict(
        hpf_hz=70.0,
        # Depth
        body_hz=140.0, body_q=0.8, body_db=4.5 * d ** 0.8,
        mud_hz=320.0, mud_q=1.0, mud_db=-2.5 * d,
        # Presence
        pres_hz=3200.0, pres_q=1.0, pres_db=4.0 * p,
        air_hz=min(11000.0, 0.45 * fs), air_db=3.0 * p ** 1.5,
        # de-esser (stronger the more presence you add)
        ess_lo=5500.0, ess_hi=min(9000.0, 0.45 * fs),
        ess_ratio=1.0 + 3.0 * p, ess_thr_rel_db=-9.0 - 3.0 * p, ess_max_red_db=9.0,
        # Control
        exp_ratio=1.0 + 1.5 * c, exp_above_floor_db=6.0, exp_max_red_db=12.0,
        exp_open_ms=3.0, exp_close_ms=120.0,
        comp_thr_db=-16.0 - 10.0 * c, comp_ratio=1.0 + 3.0 * c, comp_knee_db=6.0,
        comp_att_ms=12.0 - 6.0 * c, comp_rel_ms=180.0 - 60.0 * c,
        # half of the "gain removed at threshold" is given back as makeup
        makeup_db=0.5 * (16.0 + 10.0 * c) * (1.0 - 1.0 / (1.0 + 3.0 * c)),
        limit_ceiling_db=-1.0, limit_lookahead_ms=2.0,
    )


# ----------------------------------------------------------------------------
# 2) BIQUADS (RBJ Audio-EQ-Cookbook) -> second-order sections
# ----------------------------------------------------------------------------
def _norm(b0, b1, b2, a0, a1, a2):
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def peaking(fs, f0, q, gain_db):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    al = np.sin(w0) / (2 * q)
    c = np.cos(w0)
    return _norm(1 + al * A, -2 * c, 1 - al * A, 1 + al / A, -2 * c, 1 - al / A)


def low_shelf(fs, f0, gain_db, S=1.0):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    c, s = np.cos(w0), np.sin(w0)
    al = s / 2 * np.sqrt((A + 1 / A) * (1 / S - 1) + 2)
    r = 2 * np.sqrt(A) * al
    return _norm(A * ((A + 1) - (A - 1) * c + r), 2 * A * ((A - 1) - (A + 1) * c),
                 A * ((A + 1) - (A - 1) * c - r), (A + 1) + (A - 1) * c + r,
                 -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - r)


def high_shelf(fs, f0, gain_db, S=1.0):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    c, s = np.cos(w0), np.sin(w0)
    al = s / 2 * np.sqrt((A + 1 / A) * (1 / S - 1) + 2)
    r = 2 * np.sqrt(A) * al
    return _norm(A * ((A + 1) + (A - 1) * c + r), -2 * A * ((A - 1) + (A + 1) * c),
                 A * ((A + 1) + (A - 1) * c - r), (A + 1) - (A - 1) * c + r,
                 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - r)


def build_eq_sos(P, fs):
    """Static part of the chain (HPF + shelves + bells) as one SOS cascade."""
    sections = [signal.butter(2, P["hpf_hz"], "highpass", fs=fs, output="sos")]
    if abs(P["body_db"]) > 1e-3:
        sections.append(peaking(fs, P["body_hz"], P["body_q"], P["body_db"]))
    if abs(P["mud_db"]) > 1e-3:
        sections.append(peaking(fs, P["mud_hz"], P["mud_q"], P["mud_db"]))
    if abs(P["pres_db"]) > 1e-3:
        sections.append(peaking(fs, P["pres_hz"], P["pres_q"], P["pres_db"]))
    if abs(P["air_db"]) > 1e-3:
        sections.append(high_shelf(fs, P["air_hz"], P["air_db"]))
    return np.vstack(sections)


# ----------------------------------------------------------------------------
# 3) DYNAMICS HELPERS
# ----------------------------------------------------------------------------
def _coef(ms, fs):
    return float(np.exp(-1.0 / (max(ms, 1e-3) * 1e-3 * fs)))


def _asym_smooth(target, c_down, c_up):
    """One-pole smoother with different coefficients when target falls / rises."""
    out = np.empty_like(target)
    s = float(target[0])
    for n in range(len(target)):
        t = target[n]
        k = c_down if t < s else c_up
        s = k * s + (1.0 - k) * t
        out[n] = s
    return out


def _onepole(x, ms, fs):
    a = _coef(ms, fs)
    return signal.lfilter([1 - a], [1, -a], x)


def estimate_noise_floor_db(x, fs, frame_ms=50.0):
    n = int(fs * frame_ms / 1000)
    m = len(x) // n
    rms = np.sqrt(np.mean(x[: m * n].reshape(m, n) ** 2, axis=1))
    return float(np.percentile(lin2db(rms), 10))


def expander(x, P, fs):
    if P["exp_ratio"] <= 1.001:
        return x
    floor_db = estimate_noise_floor_db(x, fs)
    thr = floor_db + P["exp_above_floor_db"]
    lvl = lin2db(_onepole(np.abs(x), 10.0, fs))
    g_db = np.where(lvl < thr, (lvl - thr) * (P["exp_ratio"] - 1.0), 0.0)
    g_db = np.maximum(g_db, -P["exp_max_red_db"])
    g_db = _asym_smooth(g_db, _coef(P["exp_close_ms"], fs), _coef(P["exp_open_ms"], fs))
    return x * db2lin(g_db)


def deesser(x, P, fs, block=32):
    """Dynamic bell: a band-pass SIDECHAIN measures sibilance, a peaking cut at the
    band centre is updated every `block` samples (this is how a real plugin does it;
    subtracting a causal band-pass does not work - its phase shift breaks the cancel)."""
    if P["ess_ratio"] <= 1.001:
        return x
    bp = signal.butter(4, [P["ess_lo"], P["ess_hi"]], "bandpass", fs=fs, output="sos")
    band = signal.sosfilt(bp, x)
    env_b = _onepole(np.abs(band), 5.0, fs)
    env_f = _onepole(np.abs(x), 5.0, fs)
    ess_db = lin2db(env_b) - lin2db(env_f)          # ~ -7 dB = pure sibilance, < -20 = vowel
    red = np.clip((ess_db - P["ess_thr_rel_db"]) * (1.0 - 1.0 / P["ess_ratio"]),
                  0.0, P["ess_max_red_db"])
    red = _onepole(red, 3.0, fs)
    f0 = float(np.sqrt(P["ess_lo"] * P["ess_hi"]))
    y = np.empty_like(x)
    zi = np.zeros((1, 2))
    for i in range(0, len(x), block):
        r = float(np.mean(red[i:i + block]))
        sos = peaking(fs, f0, 1.2, -r) if r > 0.05 else np.array([[1.0, 0, 0, 1.0, 0, 0]])
        y[i:i + block], zi = signal.sosfilt(sos, x[i:i + block], zi=zi)
    return y


def compressor(x, P, fs):
    if P["comp_ratio"] <= 1.001:
        return x
    T, R, W = P["comp_thr_db"], P["comp_ratio"], P["comp_knee_db"]
    xd = lin2db(x)
    over = xd - T
    y = np.where(2 * over < -W, xd,
        np.where(2 * np.abs(over) <= W,
                 xd + (1.0 / R - 1.0) * (over + W / 2.0) ** 2 / (2.0 * W),
                 T + over / R))
    c = y - xd                                     # <= 0 dB
    c = _asym_smooth(c, _coef(P["comp_att_ms"], fs), _coef(P["comp_rel_ms"], fs))
    return x * db2lin(c + P["makeup_db"])


def limiter(x, P, fs):
    N = max(2, int(fs * P["limit_lookahead_ms"] / 1000))
    ceil = float(db2lin(P["limit_ceiling_db"]))
    need = np.minimum(1.0, ceil / np.maximum(np.abs(x), EPS))
    padded = np.concatenate([need, np.ones(N - 1)])
    gmin = np.lib.stride_tricks.sliding_window_view(padded, N).min(axis=1)
    g = np.convolve(np.concatenate([np.ones(N - 1), gmin]), np.ones(N) / N, mode="valid")
    return x * g


# ----------------------------------------------------------------------------
# 4) PUBLIC ENTRY POINT
# ----------------------------------------------------------------------------
def process(x, fs, depth, presence, control, return_params=False):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:                                  # channels processed independently
        outs = [process(x[:, i], fs, depth, presence, control) for i in range(x.shape[1])]
        return np.stack(outs, axis=1)
    P = map_knobs(depth, presence, control, fs)
    hpf = signal.butter(2, P["hpf_hz"], "highpass", fs=fs, output="sos")
    y = signal.sosfilt(hpf, x)
    y = expander(y, P, fs)
    eq = build_eq_sos(P, fs)[1:]                     # drop HPF, already applied
    if len(eq):
        y = signal.sosfilt(eq, y)
    y = deesser(y, P, fs)
    y = compressor(y, P, fs)
    y = limiter(y, P, fs)
    return (y, P) if return_params else y


def eq_response_db(P, fs, freqs):
    """Net static-EQ magnitude (dB) at the given frequencies - for building presets."""
    sos = build_eq_sos(P, fs)
    _, h = signal.sosfreqz(sos, worN=freqs, fs=fs)
    return 20 * np.log10(np.abs(h))


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("usage: voice_macro.py in.wav out.wav depth presence control   (each 0..1)")
        sys.exit(1)
    fs, data = wavfile.read(sys.argv[1])
    if data.dtype.kind == "i":
        data = data / float(np.iinfo(data.dtype).max)
    out = process(data.astype(np.float64), fs, *map(float, sys.argv[3:6]))
    wavfile.write(sys.argv[2], fs, out.astype(np.float32))
    print("wrote", sys.argv[2])
