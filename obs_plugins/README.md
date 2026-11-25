# Voice Match OBS Plugin — Engineering Handover v0.4

## Overview

Two OBS audio filters for Windows x64:
1. **Voice Match** — three sliders (Depth, Presence, Control) to match mic audio to Zoom H1n reference
2. **Voice Isolation** — one toggle to keep speech, remove steady noise via RNNoise

Both share a native C DSP engine. Python controller handles offline rendering.

## Architecture

```
OBS Audio Pipeline:
  Source → [Isolation filter] → [Voice Match filter] → Mix
                                    │
                                    └── DSP Chain:
                                          1. HPF 70 Hz
                                          2. EQ cascade (body/mud/presence/air)
                                          3. Compressor (linked RMS, 12/120ms)
                                          4. Loudness lander (-17.92 LUFS target)
                                          5. True-peak limiter (-2.0 dBTP ceiling)
```

## Files

| Path | Purpose |
|------|---------|
| `voice-match-plugin/src/vm_filter.c` | Main filter implementation |
| `voice-match-plugin/src/plugin-main.c` | Plugin entry point |
| `voice-match-plugin/src/vmcore/profile.{h,c}` | Reference profile |
| `voice-match-plugin/CMakeLists.txt` | Build configuration |
| `voice-match/voice_match_render.py` | Python offline renderer |
| `voice-isolation/voice_isolation.lua` | OBS Lua script |
| `reference/Zoom-H1n-Voice-Reference.json` | Target profile |

## Building

Requires:
- CMake 3.16+
- OBS Studio source (for libobs headers)
- Visual Studio 2022 or MinGW-w64
- OBS SDK installed

```bash
cmake -B build -S . -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```

Output: `build/bin/64bit/voice-match.dll`

Install to: `C:\Program Files\obs-studio\obs-plugins\64bit\`

## Reference Contract

| Parameter | Target |
|-----------|--------|
| Integrated loudness | -17.92 LUFS |
| True-peak ceiling | -2.0 dBTP |
| Internal limiter | -2.3 dBTP |
| Loudness tolerance | ±0.25 LU (offline) |
| Tone MAE | ≤2 dB |
| 3.2–4.48 kHz residual | ≤2 dB |
| Match latency | ≤15 ms |
| Isolation latency | ≤60 ms |

## Known Limitations

1. **No build toolchain on this machine** — C plugins cannot be compiled here. Source is complete but untested for compilation.
2. **RNNoise integration** — Uses OBS's built-in suppression; custom DeepFilterNet not yet integrated.
3. **Live loudness metering** — Approximate via RMS; not BS.1770-compliant in real-time.

## Validation

Run the Python renderer against test audio:
```bash
python voice_match_render.py input.wav --output matched.wav --json report.json
```

Check output against reference measurements.

## Commit History

See git log for engineering iterations.

---

**Status**: Source complete. Compilation blocked: no CMake/MSBuild/gcc available on build host.
