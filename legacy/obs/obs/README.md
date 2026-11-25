# obs/ — Voice Match and Voice Isolation for OBS

Two audio tools for OBS Studio that share one goal: make any microphone
sound like the **Zoom H1n voice reference**, and keep only your voice when
isolation is toggled on. This branch revision (v0.3) fixes the loudness
failure documented in the render evidence: a zero-overshoot true-peak
limiter plus a verify-and-correct loudness lander replace the gain clamp
and the loudnorm fallback. All numbers: [validation/REPORT.md](validation/REPORT.md).

## What is here

| Path | What it is |
|---|---|
| `blueprints/voice-match-blueprint.json` | App 1 spec, v0.3, revised as sound engineer: diagnosis of the 4.8 LU miss, the fix, slider table + opinion, measured results |
| `blueprints/voice-isolation-blueprint.md` | App 2 spec, v0.3: one toggle, RNNoise via OBS's own filter, hotkey, validation framework |
| `plugin/` | Native OBS audio filter (C11): `src/vmcore/` is the header-only DSP core (bit-exact with the matcher oracle, 0.000 dB parity); `src/vm_filter.c` is the OBS glue (3 sliders, listen → solve → fade in, lander, limiter); template CMake + buildspec.json |
| `plugin/tests/test_vmcore.c` | Standalone tests: analyser/curve parity vs the oracle, limiter worst cases |
| `script/voice_match.py` | OBS Python script (App 1 quick path): analyse a raw mic WAV, render the matched WAV (exact), push an *approximate* mapping into OBS's stock filters |
| `script/isolate_voice.lua` | OBS Lua script (App 2): the isolation toggle + hotkey |
| `tools/` | render_matched.py (revised pipeline), report_card.py, make_test_wavs.py, parity_check.sh, matcher copy |
| `validation/REPORT.md` | Every measured number, honest limits section |
| `attachments/` | The uploaded files this work is based on, unmodified |

## The three sliders (App 1)

| Slider | Default | What it scales |
|---|---|---|
| Depth | 75 | body (140 Hz) + mud (320 Hz) solved gains |
| Presence | 75 | presence (3.2 kHz) + air (10 kHz shelf) solved gains |
| Control | 45 | compressor ratio only (threshold stays as solved) |

They are the matcher's own percentages. Loudness is computed, not a slider.

## Chain order in OBS

1. Voice Isolation (App 2)
2. Voice Match (App 1)
3. Nothing else that changes gain, compression or limiting on that source.

## Building the plugin

Same as the OBS plugin template (Windows: Visual Studio 2022 + CMake
3.28+; the `cmake/` and `build-aux/` trees are the template's):

```
cmake --preset windows-x64
cmake --build --preset windows-x64
```

The DSP core can be built and tested with no OBS at all:

```
gcc -O2 -std=c11 -I plugin/src -o /tmp/test_vmcore plugin/tests/test_vmcore.c -lm
/tmp/test_vmcore limiter
bash tools/parity_check.sh /home/z/my-project/work/val   # C vs Python oracle
```

## Honest status

- Offline pipeline (the maths the plugin runs): validated to ≤0.06 LU
  loudness error under a hard −2.00 dBTP ceiling on the reproduced failure
  case and five more takes; C core at 0.000 dB parity with the matcher.
- Plugin binary: not compiled against the OBS SDK in this Linux sandbox —
  needs a Windows/macOS build host. The glue is syntax-checked against
  real libobs headers and logic-checked against a mock surface.
- Live learning (45 s listen, lock, fade) and the 8-hour soak: not yet
  tested. The script paths run anywhere OBS runs Python/Lua.
