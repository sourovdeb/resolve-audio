# Voice Macro: a 3-knob voice enhancer for DaVinci Resolve

Prepared 2026-11-25 for Resolve 21.x (21.2 is the current release as of 5 Nov 2026).
Status of everything below: the DSP math is **built and bench-tested in Python**. Everything that touches Resolve itself (Fairlight preset values, VST3 skeleton, scripting calls) is **not tested inside Resolve**. Each section says which is which.

---

## 0. Bottom line

1. **Neither SDK in the notes you pasted can build this.** OpenFX (Dehancer-style) processes *images*. Workflow Integrations (Magic Scripts-style) is a UI and automation layer around the scripting API. Neither one inserts audio DSP into Fairlight's signal path. Their closing question, "image effect node or floating UI tool?", is a false choice for an audio goal.
2. **"A plugin that drives Resolve's own EQ and dynamics" is not possible through any public interface I could find.** Fairlight per-parameter control is not exposed to scripting. What is exposed: apply a saved Fairlight preset wholesale, voice isolation on/off + amount, dialogue leveler, clip volume. (Sources in section 18; the scripting claims come from third-party wrappers and should be confirmed against `Developer/Scripting/README.txt` in your install.)
3. **The idea splits cleanly in two.** The *logic* (3 knobs mapped to EQ and dynamics values with simple maths) is portable and is done and tested here. The *delivery* has four options (section 3).
4. **Recommended order:** (a) run the Python prototype on your own clips and tune the numbers, (b) turn the result into 3 Fairlight presets using Resolve's built-in tools (works today, any OS, free or Studio), (c) only if you still want real knobs, build a VST3 on **Windows**.
5. **Honest expectations:** this chain gets a cheap mic *noticeably closer* to a "broadcast" voice. It will not turn it into a Shure SM7B, and nothing in EQ/dynamics can fix room echo, clipping or heavy noise.

### My probability estimates (judgement, not measurements)

| Outcome | Estimate | Why |
|---|---|---|
| A plugin built with OFX or Workflow Integrations drives Resolve's built-in Fairlight EQ/dynamics from 3 knobs | **<=3%** | OFX is video-only; scripting has no per-parameter Fairlight access (per third-party docs) |
| Path A (hand-built Fairlight presets from this map) sounds clearly better than the raw clip on a typical home recording, in a loudness-matched A/B | **~75%** | Standard voice chain; fails mainly on noisy, echoey or clipped sources |
| Same, on a noisy / reverberant / clipped source | **~40%** | Compression raises what is already wrong |
| Path B VST3 loads and works in Resolve **on Windows**, 3 knobs, you have Python/Linux dev experience but no C++/JUCE experience | **~80% within 4 to 6 weekends** | Well-trodden path; most risk is C++ toolchain and DSP debugging |
| Path B on **Linux** via the community bridge, stable across Resolve updates | **~30 to 40%** | Unofficial, patches Resolve at launch, broke on 21.1, deadlock history (section 10.3) |
| Listeners cannot tell the processed cheap mic from an SM7B-class mic in a blind test | **<5%** | Capsule, distance and room are not fixable in post |
| Listeners prefer processed over raw, loudness-matched, decent source | **~70 to 80%** | |

---

## 1. What I checked, and how much to trust it

| Claim | Basis | Confidence |
|---|---|---|
| Fairlight hosts VST3 on macOS and Windows (added in 17.4) | Blackmagic product manager forum post | High |
| Fairlight has 6-band parametric EQ on every track and clip, dynamics (expander/gate, compressor, limiter), and FX such as de-esser, de-hummer, noise reduction | Blackmagic Fairlight product pages | High |
| Presets can be saved for EQ and dynamics windows and copied between tracks | Same pages | Medium-high (UI details not verified) |
| Linux Resolve has no native third-party audio plugin hosting; a community bridge exists | Bridge repo changelog (read in full) + a KVR forum user report | Medium-high. KVR's product page lists Resolve 21 as a Linux host, which conflicts; check *Preferences > Audio Plugins* on your install |
| The community bridge needed a patch for 21.1 and had a freeze/deadlock | Same changelog (v0.3.0, v0.3.0.1) | High on the repo's claims; **unknown whether it works on 21.2** (I did not check) |
| Scripting: `GetFairlightPresets` / `ApplyFairlightPresetToCurrentTimeline` need Resolve 20.2.2+; voice isolation setters need 20.1+; "EQ is not scriptable" | Third-party wrappers and skill notes | Medium. Confirm against Blackmagic's own README |
| 21.1 release notes list "advanced scripting now requires Studio" | A release-notes summary | Low-medium: meaning of "advanced" unclear |
| Many scripting setters return True and do nothing | Third-party skill notes | Medium. Treat read-back verification as mandatory |

---

## 2. Reality check: what each SDK can do for audio

| Interface | What it is | Can it add audio DSP to Fairlight? | Can it set Fairlight EQ/compressor parameters? |
|---|---|---|---|
| **OpenFX (OFX)** | C++ image-effect plugins (Dehancer Pro). Runs on Edit/Color/Fusion image buffers, GPU via CUDA/Metal/OpenCL | **No** (video only) | No |
| **Workflow Integrations** | Panels/apps (Electron, Python) that talk to Resolve through the scripting API. Typically needs Studio | **No** (no audio processing hook) | Only what the scripting API exposes (see below) |
| **Scripting API** (Python/Lua) | Controls projects, timelines, render queue | No | **No per-parameter access.** Exposed: apply saved Fairlight preset (20.2.2+), voice isolation state, dialogue leveler, volume |
| **VST3 / AU** | Audio plugin formats Fairlight hosts | **Yes** (your own DSP) | Not applicable: it *is* the effect |

The practical consequence: **a "Resolve audio plugin" with knobs is a VST3 (Windows/macOS) that contains its own DSP.** It cannot call Resolve's EQ. It can, however, run the *same kind of maths* (biquad EQ, compressor, de-esser) in a few hundred lines. That is what section 5 to 7 define.

---

## 3. The four delivery paths

| | **A. Fairlight preset pack** | **B. Own VST3 plugin** | **C. Script helper** | **D. Offline render** |
|---|---|---|---|---|
| Real knobs in the UI | No (3 presets + manual interpolation) | **Yes** | No | No |
| Uses Resolve's built-in effects | **Yes** | No (own DSP) | Yes (via whole-preset apply) | No |
| Windows | Yes | **Yes** | Yes | Yes |
| Linux | Yes | Only via unofficial bridge | Yes | Yes |
| Free edition | Yes | Believed yes (verify) | Limited (scripting rules changed in 21.1) | Yes |
| Code needed | None | C++ (JUCE) or Faust | Python | Python / ffmpeg |
| Effort (my estimate) | 2 to 4 hours | 4 to 6 weekends | 1 weekend | 1 hour (script exists) |
| Main risk | Fairlight UI limits on band types | Toolchain, DSP bugs, Resolve host quirks | Whole-timeline preset overwrite; setters that silently do nothing | Leaves Resolve; re-import step |

**Decision tree**

- Do you need *real knobs inside Fairlight*? No -> **A** (then **D** for batch jobs). Yes -> go on.
- Are you on Windows or macOS for Resolve? Yes -> **B**. No (Linux only) -> expect pain; do **A**, or run Resolve for audio on a Windows machine. **B on Linux is a project of its own** (section 10.3).
- Do you want automation (apply a look to many timelines)? -> add **C** on top of A.

---

## 4. Define the target before tuning anything

You wrote "similar to Zoom H1n and Shure". Two things to be clear about:

- The Zoom H1n is a budget handheld recorder with built-in X/Y condenser mics. It is not what makes the deep "radio" sound. The classic broadcast/audiobook sound is a **dynamic mic used close** (SM7B is the usual example): proximity warmth around 100 to 200 Hz, a smooth presence region around 3 to 5 kHz, restrained highs, and consistent level from compression.
- **Assumption used here:** source = cheaper mic; target = warm, controlled, close-mic broadcast voice. If you meant something else, only the numbers in `map_knobs()` change.

**The best way to say "sound like X" in maths is reference matching:** record the same sentence on the target mic and the cheap mic, compare long-term average spectra in 1/3-octave bins, and fit the difference with your 6 EQ bands. `match_eq.py` (section 13) does that and was smoke-tested. It matches *tone*, not capsule behaviour or room.

---

## 5. The three knobs

All knobs run 0 to 1. **0 means that stage is off** (verified: with all knobs at 0 the 300 Hz to 4 kHz level changes by 0.00 dB; only the fixed 70 Hz high-pass remains).

```
input -> HPF 70 Hz -> expander -> EQ (body, mud, presence, air) -> de-esser -> compressor + makeup -> limiter -> output
                          ^                ^                          ^              ^
                        Control          Depth / Presence          Presence        Control
```

| Knob | Stages it drives | You hear | Typical sweet spot |
|---|---|---|---|
| **1. Depth** | Body bell 140 Hz (up to +4.5 dB), mud cut 320 Hz (up to -2.5 dB) | Warmer, "bigger" voice | 0.3 to 0.6 |
| **2. Presence** | Presence bell 3.2 kHz (up to +4 dB), air shelf 11 kHz (up to +3 dB), de-esser gets stronger as Presence rises | Clearer, closer, still not sizzly | 0.3 to 0.6 |
| **3. Control** | Expander (noise between words), compressor ratio/threshold/attack/release, automatic makeup | Even level, "radio" consistency | 0.3 to 0.5 |

### Parameter map (this is the "logic"; every number is editable in `map_knobs()`)

With `d`, `p`, `c` = Depth, Presence, Control:

| Parameter | Formula | Range |
|---|---|---|
| High-pass | fixed 70 Hz, 2nd order | |
| Body bell | 140 Hz, Q 0.8, gain = 4.5 * d^0.8 dB | 0 to +4.5 dB |
| Mud bell | 320 Hz, Q 1.0, gain = -2.5 * d dB | 0 to -2.5 dB |
| Presence bell | 3200 Hz, Q 1.0, gain = 4.0 * p dB | 0 to +4 dB |
| Air shelf | min(11 kHz, 0.45 * fs), gain = 3.0 * p^1.5 dB | 0 to +3 dB |
| De-esser | band 5.5 to 9 kHz sidechain; ratio = 1 + 3p; threshold = -9 - 3p dB (relative); max reduction 9 dB | off to 4:1 |
| Expander | threshold = noise floor + 6 dB; ratio = 1 + 1.5c; max reduction 12 dB; open 3 ms, close 120 ms | off to 2.5:1 |
| Compressor | threshold = -16 - 10c dBFS; ratio = 1 + 3c; knee 6 dB; attack = 12 - 6c ms; release = 180 - 60c ms | off to 4:1 |
| Makeup | 0.5 * (-threshold) * (1 - 1/ratio) dB | 0 to ~9.8 dB |
| Limiter | ceiling -1 dBFS, 2 ms lookahead | |

Why these shapes: Depth uses an exponent < 1 so the first part of the knob does something audible; the mud cut is coupled to the body boost so Depth does not just turn the voice boomy; the de-esser is coupled to Presence because boosting 3 kHz and above makes "s" sounds worse; Control's makeup is a rule of thumb (give back half the gain the compressor removes at threshold), then you trim by ear.

---

## 6. The maths (reference)

**Biquad EQ (RBJ Audio EQ Cookbook).** For sample rate `fs`, centre `f0`, gain `G` dB: `A = 10^(G/40)`, `w0 = 2*pi*f0/fs`, `alpha = sin(w0)/(2Q)`. Peaking filter:
`b0 = 1 + alpha*A, b1 = -2cos(w0), b2 = 1 - alpha*A, a0 = 1 + alpha/A, a1 = -2cos(w0), a2 = 1 - alpha/A`, then divide all by `a0`. Shelf formulas are in `voice_macro.py`.

**Compressor static curve with soft knee** (Giannoulis et al.). With input level `x` (dB), threshold `T`, ratio `R`, knee width `W`:
- `2(x - T) < -W`: output = `x`
- `|2(x - T)| <= W`: output = `x + (1/R - 1) * (x - T + W/2)^2 / (2W)`
- `2(x - T) > W`: output = `T + (x - T)/R`

Gain reduction `c = output - x` (<= 0 dB). Smooth `c` with a one-pole filter, using the attack coefficient when reduction is increasing and the release coefficient when it is decreasing. Coefficient from time: `k = exp(-1 / (t_seconds * fs))`.

**Expander.** Below `threshold`, gain in dB = `(level - threshold) * (ratio - 1)`, clamped to a maximum reduction. The threshold follows a measured noise floor (10th percentile of 50 ms frame levels) + 6 dB. *In a real-time plugin you cannot measure the floor in advance: use a fixed threshold or a "learn noise" button.*

**De-esser.** Sidechain band-pass 5.5 to 9 kHz. `ess = level_band_dB - level_fullband_dB` (about -7 dB for a pure "s", below -20 dB for vowels). `reduction = clamp((ess - threshold_rel) * (1 - 1/ratio), 0, max)`. Apply `reduction` as the (negative) gain of a **peaking bell at the band centre (about 7 kHz, Q 1.2)**, updated every 32 samples.
*Lesson from testing:* the first version subtracted the band-passed signal from the input. That measured about 0.1 dB of reduction because a causal band-pass is not zero-phase and the subtraction does not cancel. The dynamic-bell version measures about 1.9 dB average reduction on sibilant bursts.

**Limiter.** Per-sample required gain `g = min(1, ceiling/|x|)`; take the minimum over the next N samples; average that over N samples. This guarantees no sample exceeds the ceiling and ramps gain smoothly. In a plugin, N-1 samples of lookahead = reported latency.

---

## 7. The prototype: `voice_macro.py` (tested)

Run:

```
pip install numpy scipy
python voice_macro.py input.wav output.wav 0.5 0.5 0.4     # depth presence control
```

Reads 16-bit or 32-bit float WAV; runs offline on mono (or stereo, channels processed independently). Pure Python loops for the dynamics: a 20-second clip takes roughly 0.1 to 1.6 seconds on the test machine. This is the *reference for the maths*, not a real-time engine.

```python
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
```

---

## 8. Bench results (what I actually ran)

**Test signal (synthetic, 20 s, 48 kHz):** a voice-like source (glottal pulse train + vowel formants + syllable level swings), "s" noise bursts placed *between* vowels, filtered to sound like a thin cheap mic (180 Hz high-pass + 1.5 kHz honk), plus pink room noise at -52 dBFS. Loudness and LRA measured with ffmpeg `ebur128`. Band levels in dB (relative), measured only where relevant (speech frames, sibilant bursts, true gaps).

| Setting | LUFS | LRA | Peak dBFS | 80-200 Hz | 220-350 Hz | 2-4.5 kHz | 5.5-9 kHz (s) | Gap noise |
|---|---|---|---|---|---|---|---|---|
| Input | -29.9 | 4.0 | -8.3 | -41.2 | -30.1 | -46.9 | -40.8 | -52.0 |
| 0 / 0 / 0 | -29.9 | 4.0 | -9.5 | -41.3 | -30.2 | -46.9 | -40.8 | -53.4 |
| Depth 1 | -30.2 | 4.2 | -8.9 | -39.6 | -30.4 | -46.9 | -40.8 | -52.9 |
| Presence 1 | -29.5 | 3.9 | -9.2 | -41.3 | -30.1 | -44.0 | -41.5 | -52.2 |
| Control 1 | -24.0 | 2.2 | -6.1 | -36.9 | -25.3 | -40.7 | -32.3 | -51.9 |
| 0.5 / 0.5 / 0.5 | -24.9 | 3.0 | -6.1 | -36.0 | -25.6 | -40.3 | -35.4 | -50.4 |
| 1 / 1 / 1 | -23.8 | 2.1 | -5.6 | -35.2 | -25.4 | -37.8 | -33.5 | -50.2 |

Static EQ response relative to the HPF-only baseline (dB):

| Freq (Hz) | 60 | 100 | 140 | 200 | 320 | 500 | 1k | 3.2k | 6k | 10k | 16k |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Depth 1 | +1.3 | +3.2 | +3.9 | +2.1 | -1.1 | -0.8 | -0.1 | 0 | 0 | 0 | 0 |
| Presence 1 | 0 | 0 | 0 | 0 | 0 | +0.1 | +0.4 | +4.0 | +1.5 | +1.5 | +2.9 |
| 0.5 / 0.5 / 0.5 | +0.7 | +1.9 | +2.3 | +1.3 | -0.4 | -0.3 | +0.1 | +2.0 | +0.7 | +0.6 | +1.0 |

**What this shows**

- Knobs at 0 are transparent apart from the 70 Hz high-pass (verified).
- Depth lifts 100 to 200 Hz and trims 320 to 500 Hz as designed. The measured 80-200 Hz band rises only +1.6 dB because my synthetic thin mic has almost nothing there. **EQ cannot create energy that was never recorded**, so a very thin source gets less "depth" than the static curve suggests.
- Presence adds about +3 dB in the 2-4.5 kHz band while sibilance ends up about 0.7 dB *lower* than the input (de-esser working: about 1.9 dB average reduction on bursts versus de-esser disabled).
- Control 1 raises level 5.9 LU and cuts loudness range 4.0 to 2.2 LU. The gap-noise level stayed essentially flat (-52.0 to -51.9) because the expander offsets the makeup gain: speech about +6 dB relative to noise in this synthetic case.
- At 1/1/1 the noise floor rises about 1.8 dB while speech rises about 9 dB. On real recordings where the noise is closer to speech level, expander + compressor will pump (section 14).
- De-esser before or after the compressor made no meaningful difference (sibilance minus presence: 4.2 dB vs 4.1 dB at 1/1/1, versus 6.1 dB with everything off).
- Limiter: on the normal clip the highest peak was -5.6 dBFS, so the limiter never had to act. Separately, I fed the same clip 12 dB and 24 dB hotter (Depth/Presence/Control 0.5): output peak held at -1.00 dBFS both times. Sample peak only, not true peak.

**What this does NOT show:** how it sounds on real speech, stereo behaviour, real-time latency, CPU load, or anything inside Resolve. A synthetic voice can validate the arithmetic, not the taste. **Step 1 for you is to run it on three real clips.**

---

## 9. Path A: build the presets with Resolve's own tools (no code)

*Values below come from `map_knobs()` and are tested in Python. How they map onto Fairlight's UI is **not verified**: control names, band types and units can differ per build. Treat as a starting point.*

Three levels, all three knobs moved together (set them independently if you prefer):

| Module (Fairlight) | Light (0.3) | Medium (0.6) | Strong (1.0) |
|---|---|---|---|
| EQ band 1: high-pass | 70 Hz | 70 Hz | 70 Hz |
| EQ band 2: bell "body" | 140 Hz, Q 0.8, +1.7 dB | +3.0 dB | +4.5 dB |
| EQ band 3: bell "mud" | 320 Hz, Q 1.0, -0.8 dB | -1.5 dB | -2.5 dB |
| EQ band 4: bell "presence" | 3.2 kHz, Q 1.0, +1.2 dB | +2.4 dB | +4.0 dB |
| EQ band 6: high shelf "air" | 11 kHz, +0.5 dB | +1.4 dB | +3.0 dB |
| De-esser (FX plug-in) | threshold so only "s" triggers; about 1 to 2 dB on "s" | 2 to 3 dB | 3 to 4 dB |
| Dynamics: expander/gate | threshold = noise floor + 6 dB, ratio about 1.45:1 | 1.9:1 | 2.5:1; limit reduction to about 12 dB |
| Dynamics: compressor | threshold -19 dBFS, ratio 1.9:1, attack 10 ms, release 160 ms, makeup +4.5 dB | -22 dBFS, 2.8:1, 8 ms, 145 ms, +7.1 dB | -26 dBFS, 4:1, 6 ms, 120 ms, +9.8 dB |
| Dynamics: limiter | ceiling -1 dBFS | same | same |

Procedure:
1. On the Fairlight page, put the clip on a mono track. Open the track EQ (double-click the EQ area) and the dynamics window.
2. Enter the Light column. If a band cannot be set to the type listed (shelf, high-pass), use the nearest band that can (often bands 1 and 6 offer the filter types) and note which one in the preset name.
3. Insert the built-in **De-Esser** and **Noise Reduction** FX on the track if the clip needs them. Do noise reduction *before* the dynamics (noise reduction after compression is much less effective).
4. **Match loudness against the bypassed track before judging** (trim the makeup until the LUFS reading is within about 0.5 LU). Louder always sounds better; unmatched A/B tests are meaningless.
5. Save the EQ and dynamics settings as presets named `VM Light`, `VM Medium`, `VM Strong` (Fairlight lets you save presets and copy settings between tracks).
6. For in-between knob positions, interpolate with the formulas in section 5 (a 10-line spreadsheet does it).

**Limits you should accept:** no single knob moving several effects at once, and no macro/link feature for Fairlight audio effects that I could find (the Macro Editor in Resolve 21 is for Fusion/video effects).

---

## 10. Path B: a real VST3 with 3 knobs

### 10.1 Choose the framework

| Option | Pros | Cons |
|---|---|---|
| **JUCE (C++)** | Industry standard, built-in IIR, compressor, gate, limiter, VST3 export, GUI | C++ toolchain; check licence terms before distributing or selling (private use is fine) |
| **Faust** | Tiny DSP programs, compiles to plugins | Not tested here; GUI and host quirks less documented |
| iPlug2 | Permissive licence | Smaller community |

The skeleton below uses JUCE because most of the DSP blocks already exist. **It has not been compiled.** Expect to fix includes and small API details.

### 10.2 Project skeleton (Windows)

Install: Visual Studio 2022 (Desktop C++ workload), CMake, JUCE (clone into `./JUCE`).

`CMakeLists.txt`
```cmake
cmake_minimum_required(VERSION 3.22)
project(VoiceMacro VERSION 0.1.0)
add_subdirectory(JUCE)

juce_add_plugin(VoiceMacro
    COMPANY_NAME "YourName"
    PLUGIN_MANUFACTURER_CODE Ynam
    PLUGIN_CODE Vmac
    FORMATS VST3 Standalone
    NEEDS_MIDI_INPUT FALSE
    PRODUCT_NAME "Voice Macro"
    COPY_PLUGIN_AFTER_BUILD TRUE)

target_sources(VoiceMacro PRIVATE PluginProcessor.cpp PluginEditor.cpp)
target_link_libraries(VoiceMacro
    PRIVATE juce::juce_audio_utils juce::juce_dsp
    PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)
target_compile_definitions(VoiceMacro PUBLIC JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
```

`PluginProcessor.h`
```cpp
#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>

class VoiceMacroAudioProcessor : public juce::AudioProcessor
{
public:
    VoiceMacroAudioProcessor();
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported (const BusesLayout&) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "Voice Macro"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}
    void getStateInformation (juce::MemoryBlock&) override;
    void setStateInformation (const void*, int) override;

    juce::AudioProcessorValueTreeState apvts;

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createLayout();
    void updateDsp();

    using Filter = juce::dsp::IIR::Filter<float>;
    using Coeffs = juce::dsp::IIR::Coefficients<float>;
    juce::dsp::ProcessorDuplicator<Filter, Coeffs> hpf, body, mud, pres, air;
    juce::dsp::NoiseGate<float> expander;      // JUCE's gate has a ratio: it behaves as a downward expander
    juce::dsp::Compressor<float> comp;         // hard knee, no auto makeup: results differ slightly from Python
    juce::dsp::Gain<float> makeup;
    juce::dsp::Limiter<float> limiter;
    double sr = 48000.0;
};
```

`PluginProcessor.cpp` (core parts)
```cpp
#include "PluginProcessor.h"
#include "PluginEditor.h"

juce::AudioProcessorValueTreeState::ParameterLayout VoiceMacroAudioProcessor::createLayout()
{
    std::vector<std::unique_ptr<juce::RangedAudioParameter>> p;
    for (auto id : { "depth", "presence", "control" })
        p.push_back (std::make_unique<juce::AudioParameterFloat> (juce::ParameterID { id, 1 }, id, 0.0f, 1.0f, 0.0f));
    return { p.begin(), p.end() };
}

VoiceMacroAudioProcessor::VoiceMacroAudioProcessor()
    : AudioProcessor (BusesProperties().withInput ("Input", juce::AudioChannelSet::stereo(), true)
                                       .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "STATE", createLayout()) {}

bool VoiceMacroAudioProcessor::isBusesLayoutSupported (const BusesLayout& l) const
{
    auto out = l.getMainOutputChannelSet();
    return (out == juce::AudioChannelSet::mono() || out == juce::AudioChannelSet::stereo())
           && out == l.getMainInputChannelSet();
}

void VoiceMacroAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    sr = sampleRate;
    juce::dsp::ProcessSpec spec { sampleRate, (juce::uint32) samplesPerBlock,
                                  (juce::uint32) getTotalNumOutputChannels() };
    for (auto* f : { &hpf, &body, &mud, &pres, &air }) { f->prepare (spec); f->reset(); }
    expander.prepare (spec); comp.prepare (spec); makeup.prepare (spec); limiter.prepare (spec);
    limiter.setThreshold (-1.0f); limiter.setRelease (50.0f);
    updateDsp();
}

void VoiceMacroAudioProcessor::updateDsp()
{
    const float d = apvts.getRawParameterValue ("depth")->load();
    const float p = apvts.getRawParameterValue ("presence")->load();
    const float c = apvts.getRawParameterValue ("control")->load();
    auto g = [] (float db) { return juce::Decibels::decibelsToGain (db); };

    *hpf.state  = *Coeffs::makeHighPass  (sr, 70.0f);
    *body.state = *Coeffs::makePeakFilter (sr, 140.0f,  0.8f, g (4.5f * std::pow (d, 0.8f)));
    *mud.state  = *Coeffs::makePeakFilter (sr, 320.0f,  1.0f, g (-2.5f * d));
    *pres.state = *Coeffs::makePeakFilter (sr, 3200.0f, 1.0f, g (4.0f * p));
    *air.state  = *Coeffs::makeHighShelf  (sr, (float) juce::jmin (11000.0, 0.45 * sr), 0.707f,
                                           g (3.0f * std::pow (p, 1.5f)));

    expander.setRatio (1.0f + 1.5f * c);
    expander.setThreshold (-50.0f);            // FIXED for now: see failure-mode F9
    expander.setAttack (3.0f); expander.setRelease (120.0f);

    const float thr = -16.0f - 10.0f * c, ratio = 1.0f + 3.0f * c;
    comp.setThreshold (thr); comp.setRatio (ratio);
    comp.setAttack (12.0f - 6.0f * c); comp.setRelease (180.0f - 60.0f * c);
    makeup.setGainDecibels (0.5f * (-thr) * (1.0f - 1.0f / ratio));
}

void VoiceMacroAudioProcessor::processBlock (juce::AudioBuffer<float>& buf, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;
    updateDsp();   // prototype only: allocates in the audio thread. Later: update only when a knob moved.

    juce::dsp::AudioBlock<float> block (buf);
    juce::dsp::ProcessContextReplacing<float> ctx (block);
    hpf.process (ctx);
    expander.process (ctx);
    body.process (ctx); mud.process (ctx); pres.process (ctx); air.process (ctx);
    // TODO: port deesser() from voice_macro.py (sidechain band-pass + dynamic peaking bell)
    comp.process (ctx);
    makeup.process (ctx);
    limiter.process (ctx);
}

juce::AudioProcessorEditor* VoiceMacroAudioProcessor::createEditor() { return new VoiceMacroEditor (*this); }
void VoiceMacroAudioProcessor::getStateInformation (juce::MemoryBlock& d)
{ if (auto xml = apvts.copyState().createXml()) copyXmlToBinary (*xml, d); }
void VoiceMacroAudioProcessor::setStateInformation (const void* data, int size)
{ if (auto xml = getXmlFromBinary (data, size)) apvts.replaceState (juce::ValueTree::fromXml (*xml)); }

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new VoiceMacroAudioProcessor(); }
```

`PluginEditor.h` (the "rectangle box with 3 knobs")
```cpp
#pragma once
#include "PluginProcessor.h"

class VoiceMacroEditor : public juce::AudioProcessorEditor
{
public:
    explicit VoiceMacroEditor (VoiceMacroAudioProcessor& p) : juce::AudioProcessorEditor (&p)
    {
        setSize (360, 170);
        const char* ids[3]   = { "depth", "presence", "control" };
        const char* names[3] = { "Depth", "Presence", "Control" };
        for (int i = 0; i < 3; ++i)
        {
            knobs[i].setSliderStyle (juce::Slider::RotaryHorizontalVerticalDrag);
            knobs[i].setTextBoxStyle (juce::Slider::TextBoxBelow, false, 70, 18);
            addAndMakeVisible (knobs[i]);
            labels[i].setText (names[i], juce::dontSendNotification);
            labels[i].setJustificationType (juce::Justification::centred);
            addAndMakeVisible (labels[i]);
            att[i] = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (p.apvts, ids[i], knobs[i]);
        }
    }
    void paint (juce::Graphics& g) override
    {
        g.fillAll (juce::Colour (0xff1e1f22));
        g.setColour (juce::Colour (0xff3a3d42));
        g.drawRoundedRectangle (getLocalBounds().toFloat().reduced (6.0f), 10.0f, 2.0f);
    }
    void resized() override
    {
        auto r = getLocalBounds().reduced (16);
        const int w = r.getWidth() / 3;
        for (int i = 0; i < 3; ++i)
        {
            auto c = r.removeFromLeft (w);
            labels[i].setBounds (c.removeFromTop (20));
            knobs[i].setBounds (c);
        }
    }
private:
    juce::Slider knobs[3];
    juce::Label labels[3];
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> att[3];
};
```
(`PluginEditor.cpp` can be a one-line file including the header.)

### 10.3 Install and test in Resolve

**Windows.** Build the VST3 target. VST3 plugins normally live in `C:\Program Files\Common Files\VST3`. Open Resolve, go to Preferences and find the audio plugin list (location of the page may differ by version: look for "Audio Plugins"), rescan, then on the Fairlight page insert the plugin from the mixer's effect slots. Verify: sound passes, knobs move, project save/reload keeps knob positions.

**macOS.** Same plugin, AU or VST3 formats; code signing/notarisation applies for distribution.

**Linux.** There is no official third-party audio plugin hosting that I could confirm. A community project ("VSTForResolveLinux") bridges VST3/VST2/CLAP into Fairlight, and has a NixOS flake. From its changelog (read in full): Resolve 21.1 added a silent gate that stopped it loading anything, worked around with an `LD_PRELOAD` library; a deadlock in Resolve's own plugin chain code was repaired in v0.3.0.1 on 12 Sep 2026 but the author lists the repair as not yet verified on a frozen session; Windows plugins go through yabridge/Wine, which adds a Wine round trip per audio block and has a crash history in the changelog. Compatibility with 21.2 is **unknown**. My advice: do not make Linux the only place your plugin can run.

---

## 11. Path C: scripting helper (thin, optional)

What the scripting API can do for audio, per third-party wrappers (names and versions as reported; **confirm in Blackmagic's README in `Help > Documentation > Developer`**):

| Action | API (reported) | Resolve version |
|---|---|---|
| List saved Fairlight presets | `Resolve.GetFairlightPresets()` | 20.2.2+ |
| Apply a preset to the current timeline | `Project.ApplyFairlightPresetToCurrentTimeline(name)` | 20.2.2+ |
| Voice isolation on a track or clip | `SetVoiceIsolationState({"isEnabled": True, "amount": 0..100})` | 20.1+ |
| Clip volume, dialogue leveler | `TimelineItem` properties | varies |
| Per-parameter EQ / compressor | **not available** | none |

Implications:
- A preset apply is **whole-mix**, so it can overwrite other tracks. Snapshot or duplicate the timeline first.
- "Interpolating a knob" would mean pre-saving a grid of presets (3 x 3 x 3 = 27) by hand, then picking the nearest. Possible, tedious, unverified.
- Read every setting back after writing it; setters are reported to return True while doing nothing.
- Since 21.1, "advanced scripting" is Studio-only per a release-notes summary. Check whether your use falls under that.

---

## 12. Path D: offline render with ffmpeg (tested)

Approximate "Medium" chain, run on the synthetic clip: **-25.1 LUFS / LRA 2.6** versus the Python reference **-24.5 LUFS / LRA 2.8**. Not identical (different detectors, different de-esser), but the same ballpark.

```
ffmpeg -i in.wav -af "highpass=f=70:poles=2,equalizer=f=140:t=q:w=0.8:g=3.0,equalizer=f=320:t=q:w=1.0:g=-1.5,equalizer=f=3200:t=q:w=1.0:g=2.4,highshelf=f=11000:g=1.4,deesser=i=0.3:f=0.5,acompressor=threshold=-22dB:ratio=2.8:attack=8:release=145:makeup=2.26,alimiter=limit=0.89:level=disabled" out.wav
```

Gotchas I hit: ffmpeg's `acompressor` takes `makeup` as a **linear multiplier** (2.26 = +7.1 dB; passing 7 gave about +17 dB and a result 9 LU too loud), and its `deesser` has its own intensity/frequency scale, so `i` and `f` are hand-picked, not derived.

Workflow: export the dialogue track, run the chain, re-import onto a spare track, level-match, compare. Useful for batch work, not for live adjustment.

---

## 13. Optional: `match_eq.py` (reference matching, smoke-tested)

Smoke test: processed a clip with Depth 1 / Presence 1 / Control 0, asked the function to recover the EQ from the before/after pair, and compared to the known curve: max error 1.14 dB across bins from 100 Hz upward (the largest error is at 6.3 kHz, where the de-esser was also working). This confirms the arithmetic. It does not confirm it will work on two *different* recordings of different material, where room, distance and content all leak into the spectra: use the same sentence, same distance, and treat the result as a starting point.

```python
"""match_eq.py - 'sound like the reference' by long-term-average-spectrum (LTAS) ratio."""
import numpy as np
from scipy import signal


def ltas_db(x, fs, nperseg=8192):
    f, pxx = signal.welch(x, fs, nperseg=nperseg)
    return f, 10 * np.log10(pxx + 1e-20)


def third_octave_curve(src, ref, fs, fmin=80.0, fmax=12000.0, limit_db=6.0):
    """dB correction (ref - src) at 1/3-octave centres, clipped so it never asks for the impossible."""
    f, s = ltas_db(src, fs)
    _, r = ltas_db(ref, fs)
    centres = 1000.0 * 2.0 ** (np.arange(-11, 11) / 3.0)
    centres = centres[(centres >= fmin) & (centres <= fmax)]
    out = []
    for c in centres:
        m = (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))
        out.append(np.mean(r[m]) - np.mean(s[m]))
    out = np.array(out)
    out -= np.median(out)                      # match shape, not absolute level
    return centres, np.clip(out, -limit_db, limit_db)
```

Use: record the same 20 to 30 seconds on both mics, call `third_octave_curve(cheap, reference, fs)`, then place EQ bands where the curve is largest (limited to +/-6 dB). Do not chase narrow dips; they are mostly room.

---

## 14. Failure-mode catalogue (branch by symptom)

| # | Scenario | Likely cause | What to do |
|---|---|---|---|
| F1 | Plugin does not appear in Fairlight (Windows) | Wrong folder, no rescan, VST2 file, plugin crashed during scan | Put the `.vst3` in the standard VST3 folder; rescan in Resolve's audio plugin preferences; test in the JUCE Standalone target first; check Resolve's log |
| F2 | Plugin appears, audio silent | Channel layout mismatch (mono track vs stereo bus), NaN in a filter, wrong bus config | Test mono and stereo tracks; add a `jassert (std::isfinite(x))` check in a debug build |
| F3 | Clicks/zipper noise when turning a knob | Filter coefficients jump | Smooth parameters (`juce::SmoothedValue`) or interpolate coefficients over a few ms |
| F4 | Audio late versus picture | Limiter lookahead not reported to the host | Call `setLatencySamples()`; verify sync with a clap test |
| F5 | "Pumping" or breathing between words | Expander threshold too close to speech, release too short, compressor release too fast | Lower Control; use real noise reduction first; lengthen release; raise expander threshold margin |
| F6 | Harsh "s", sizzle | Presence too high for this mic, de-esser threshold, air shelf | Lower Presence; set de-esser threshold lower; reduce the 11 kHz shelf |
| F7 | Boomy or muddy at high Depth | Room modes, proximity effect already present on source | Lower Depth; shift the mud bell 250 to 400 Hz and widen it |
| F8 | Depth knob does almost nothing | Source mic or file has no energy below 150 Hz (cheap mics, heavy HPF in camera) | Expected: EQ cannot create what was not recorded. Gain-match and consider a gentle saturation stage instead |
| F9 | Results change clip to clip; expander misbehaves | Noise floor estimated per file in the prototype; a plugin cannot do that | Use a fixed threshold per preset, or add a "learn noise" button capturing 2 s of room tone |
| F10 | Noise gets louder with Control | Compressor + makeup raise everything below the threshold | Noise reduction first (built-in FX or Voice Isolation, Studio), then Control; reduce makeup |
| F11 | Voice sounds watery or odd after Voice Isolation + this chain | AI isolation already changed the spectrum; EQ on top exaggerates artefacts | Isolate first, then EQ with lower Presence; A/B each stage |
| F12 | Preset apply (Path C) wiped other tracks' settings | Presets are whole-mix | Duplicate the timeline first; test on a copy |
| F13 | Scripting call returns True, nothing changed | Reported behaviour of several setters | Always read back and compare |
| F14 | Works on 44.1 kHz, strange on 48 kHz or 96 kHz | Frequencies near Nyquist, fixed constants | Compute coefficients from `fs`; air shelf is clamped to 0.45 * fs (done in the prototype) |
| F15 | Output clips or is quiet | Makeup + EQ boosts stack | Limiter at -1 dBFS is in the chain; final loudness normalisation is separate (see section 15) |
| F16 | Source is clipped / heavy echo / strong background music | Not fixable by EQ and dynamics | Re-record, or use a dedicated repair tool; do not push Control |
| F17 | Resolve update breaks the Linux bridge | Resolve internals changed (this happened in 21.1) | Pin your Resolve version, or use Windows |
| F18 | Stereo file with mono voice sounds wide or unstable | Two channels processed with independent detectors | Link detectors (use the mean level) or convert to mono before the chain |
| F19 | Fairlight band cannot be set to the type in the table | Band-type restrictions per band | Use the closest available type; note it in the preset name |

---

## 15. Validation protocol (so "better" is measured, not hoped)

1. **Test set:** four clips of your own voice, 20 to 30 s each: quiet room; typical room; noisy room; sibilant sentence. Same mic, same distance.
2. **Level-match** every processed version to within 0.5 LU of the unprocessed version (Resolve's loudness meter or ffmpeg `ebur128`).
3. **Blind A/B:** have someone else play two versions in random order on headphones and a phone speaker; record the picks. Aim for at least 7 of 10 preferring processed.
4. **Objective checks:** peak at or below -1 dBFS; no clipping; spectrum plot before/after; sibilance not worse; noise floor between words not worse than the input.
5. **Stop rule:** if the quiet-room clip does not improve in a level-matched A/B, tune the map before building anything else.
6. **Loudness target (pick one):** podcast about -16 LUFS integrated; audiobook delivery specs differ by platform. ACX, for example, publishes RMS, peak and noise-floor limits: check the current ACX spec before finalising.

---

## 16. Roadmap (my estimates; adjust to your pace)

| Step | Output | Time |
|---|---|---|
| 1. Run `voice_macro.py` on 3 real clips, tune `map_knobs()` | Numbers you like | 1 to 3 h |
| 2. Reference match (`match_eq.py`) against a clip from your target mic | Tone targets | 1 h |
| 3. Build Light/Medium/Strong presets in Fairlight (Path A) | Usable today | 2 to 4 h |
| 4. Validate with the section 15 protocol | Go / no-go for a plugin | 2 h |
| 5. JUCE skeleton: build, load in Resolve (Windows), knobs work | Passing audio | 1 to 2 weekends |
| 6. Port the de-esser and fixed-threshold expander; smooth parameters; latency | Feature-complete | 2 to 3 weekends |
| 7. Presets inside the plugin (Light/Medium/Strong), saved state | v0.1 | 1 weekend |

---

## 17. What I need from you to narrow this down

1. **Resolve edition and OS** for the machine that will run it (Free or Studio; Windows, macOS or Linux). This decides between Path B and Path A.
2. **Your source mic** (model) and a 20 s sample sentence, plus **a reference clip** from the target sound if you have one.
3. **Mono or stereo** timeline for voice, and the **loudness target** (podcast, audiobook, video).
4. **Do you want to sell or share the plugin?** (licence choice for JUCE or another framework).

---

## 18. Sources

- Blackmagic forum, VST3 added for Mac/Windows in 17.4: https://forum.blackmagicdesign.com/viewtopic.php?p=1008934
- Blackmagic Fairlight overview (EQ, dynamics, de-esser, noise reduction, presets): https://www.blackmagicdesign.com/products/davinciresolve/fairlight
- Community Linux bridge changelog (21.1 gate, deadlock, NixOS): https://github.com/JaySNL/VSTForResolveLinux
- KVR forum, Linux users on Resolve and VST: https://www.kvraudio.com/forum/viewtopic.php?p=9233265 ; KVR host listing (conflicting Linux claim): https://www.kvraudio.com/product/davinci-resolve-by-blackmagic-design
- Scripting wrappers (preset and voice isolation methods, versions): https://wheheohu.github.io/pybmd/ ; https://github.com/lordhoell/davinci-resolve-mcp ; https://github.com/samuelgursky/davinci-resolve-mcp
- Resolve 21.1 and 21.2 release summaries: https://www.redsharknews.com/davinci-resolve-21.1-new-features-release ; https://www.redsharknews.com/davinci-resolve-21-2-whats-new
- RBJ Audio EQ Cookbook (biquad formulas); Giannoulis, Massberg, Reiss, "Digital Dynamic Range Compressor Design" (compressor curve and smoothing).
- Your pasted notes: OpenFX 1.5.1 docs (Academy Software Foundation) and Resolve's local `Developer/OpenFX` and `Developer/Workflow Integrations` folders.
