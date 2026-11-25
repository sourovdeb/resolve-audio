# Voice Match & Voice Isolation for OBS — Validation Report

**Date:** 2026-11-25 · **Branch:** `obs` · **Revision:** blueprint v0.3
**Environment:** Linux sandbox, Python 3.12, numpy 2.1.3, FFmpeg (system), gcc 12.
**Authority:** `implementation/matcher/match_voice.py` on `main` (the oracle). Every number below was computed, not estimated.

## 1. The failure this revision fixes

The supplied render evidence showed the primary pass (EQ + static gain) missing the loudness target by ~4.8 LU because gain was clamped by peak headroom, and the loudnorm fallback landing 0.73 LU low with a −1.90 dBTP overshoot of a −1.92 ceiling.

**Root cause 1 — PLR conflict.** The device input's peak-to-loudness ratio (~20.2 dB) is wider than the reference's (16.06 dB). A static gain that respects −2.0 dBTP cannot close a 4.8 LU loudness gap. The two goals conflict unless a limiter owns the ceiling.

**Root cause 2 — FFmpeg alimiter overshoots.** Measured directly this session, driving `user_case.wav` at +2.4 dB through alimiter with `level=0`:

| attack | release | limit | measured true peak |
|---|---|---|---|
| 5 ms | 60 ms | −2.00 dBFS | **+0.03 dBTP** |
| 5 ms | 60 ms (asc=1) | −2.00 dBFS | +0.03 dBTP |
| 5 ms | 200 ms | −2.00 dBFS | +0.03 dBTP |
| 1 ms | 60 ms | −2.20 dBFS | +0.01 dBTP |

Across every attack/release/asc combination tested, alimiter overshoots its `limit` by ~2.0–2.1 dB. It cannot hold a true-peak ceiling; using it as the safety stage (directly or inside loudnorm) guarantees the "0.02 dB overshoot" seen in the evidence.

## 2. The fix

1. **Zero-overshoot limiter (offline: numpy; plugin: C).** Per-sample needed gain = `ceiling / env4x` where `env4x` is the 4×-oversampled linked magnitude; the applied gain at sample *i* is the **minimum over the 5 ms lookahead window**, smoothed on the release edge only (60 ms). Output is ≤ ceiling by construction. Unit tests (both numpy and C): full-scale 220 Hz sine, +3 dB overdriven sine, 5 kHz sine, 1.5× noise burst — all four land at **exactly −2.000 dBFS**.
2. **Verify-and-correct loudness lander (offline).** Render → measure (ffmpeg ebur128) → correct gain → re-render, ≤3 iterations, converge threshold 0.25 LU. Live twin: slow integrator (±1 dB/s up, −3 dB/s down, holds in silence, K-weighted short-term).
3. The loudnorm fallback is retired: with the ceiling guaranteed, nothing needs rescuing.

## 3. Results: reproduced failure case

Synthetic device take built to match the evidence's device MOV (−21.05 LUFS / −0.77 dBTP): bursts at −0.8 dBFS over a −21 LUFS body.

| Stage | Integrated | True peak | Verdict |
|---|---|---|---|
| Reproduced input `user_case.wav` | −20.92 LUFS | −0.98 dBTP | matches the evidence's device MOV |
| Old pipeline (matcher match) | −22.38 LUFS | −2.00 dBTP | **fails loudness by 4.46 LU** (gain clamped by headroom) |
| Revised pipeline (limiter + lander) | **−17.98 LUFS** | **−2.00 dBTP** | **error 0.06 LU, ceiling held exactly, one lander pass** |

## 4. Results: full matrix

Synthetic 90 s speech-like takes (48 kHz stereo, sentence envelopes with pauses, wandering f0, reference-shaped excitation; `scripts/make_test_wavs.py`).

| Take | Source | Old output | Revised output | Error | Spread (ref 11.96) |
|---|---|---|---|---|---|
| device_take | −18.51 / −9.12 | −17.92 / −8.26 | −17.92 / −8.26 | 0.00 LU | 9.48 |
| headset_quiet | −21.04 / −9.12 | −17.91 / −5.41 | −17.91 / −5.41 | 0.01 LU | 6.51 |
| hot_wide | −22.50 / −9.12 | −17.92 / −3.56 | −17.92 / −3.56 | 0.00 LU | 9.16 |
| hot_wide2 (soft-clipped) | −13.84 / −1.57 | −17.92 / −4.28 | −17.92 / −4.28 | 0.00 LU | 9.16 |
| sliders 0/0/0 | −18.51 / −9.12 | — | −17.92 / −8.59 | 0.00 LU | — |
| sliders 100/100/100 | −18.51 / −9.12 | — | −17.92 / −8.17 | 0.00 LU | — |

Note: on the non-crowded takes the old pipeline already landed (its clamp never engaged); the revision's win is that the ceiling-hugging cases (the device-MOV scenario, i.e. the real one) now land too, with no overshoot. The loudnorm fallback is never invoked.

Slider behaviour: presence-band (3.2–4.48 kHz) delta vs reference moves 4.43 dB (sliders 0) → 4.23 dB (sliders 100) — monotone, no discontinuities. Compressor correctly stays off (ratio 1.0) on all synthetic takes because their spreads (6.4–9.6 dB) are already within the reference's 11.96 dB; the matcher's rule (`excess = max(0, spread_src − 11.96 − 1)`) produces ratio 1.0, verified in the curve JSONs.

Presence caveat, stated honestly: the +4.2–4.4 dB residual at 4.48 kHz on these synthetic takes mirrors the "+4.7–5.8 dB forward" flag in the real evidence. It is the 4-filter fit's residual on this material shape (the fit anchors 500–1750 Hz and spends its four caps there), not a bug, and not something a slider should paper over — at slider 100 the correction is the matcher's own solved curve, nothing added.

## 5. Results: C core parity with the Python oracle

`obs/plugin/src/vmcore/` (header-only C11: FFT, MT19937, band analyser, gate, curve solver) vs `match_voice.py`, same WAV, same 24 kHz f32 stream:

| Take | Worst band error | speechRms70 error | speechSpread error | Curve match |
|---|---|---|---|---|
| device_take | **0.000 dB** | 0.000 | 0.000 | identical (all 6 values) |
| headset_quiet | **0.000 dB** | 0.000 | 0.000 | identical |
| hot_wide | **0.000 dB** | 0.000 | 0.000 | identical |

Example: device_take curve — oracle `{body 0.69, mud 1.56, presence 1.79, air 0.94, threshold −20.6, ratio 1.0}` = C, identical.

Two oracle quirks had to be replicated exactly to reach zero (documented in the blueprint's `authority.quirks_replicated`):

1. **Bit-reversed window indexing.** `spectrum()` computes `values = [samples[rb[i]*ch+off] * window[rb[i]] ...]` — the Hann window is applied at the *bit-reversed* index. A textbook natural-index window diverges by up to 55 dB on the 6.4–10.9 kHz bands.
2. **CPython MT19937 seeding.** `random.Random(16)` is `init_by_array([16])`, not the Knuth direct seed; and `_randbelow(n)` rejects on `getrandbits(n.bit_length())`. Both implemented; first five raw outputs match CPython exactly (1552728491, 2015295599, …).

## 6. What is and is not proven

**Proven (this session, numbers above):** the revised offline pipeline lands ≤0.06 LU under a hard −2.00 dBTP ceiling on the reproduced failure case and five more takes; the C core is bit-faithful to the oracle; the limiter holds the ceiling on worst-case signals; sliders behave monotonically.

**Not yet proven (needs a Windows/macOS host):** the plugin binary loading in OBS (compiled here only against mocked headers — the sandbox lacks the OBS SDK), the live learning path (45 s listen → lock → 2 s fade), the 8-hour soak, and real-microphone listening tests. The script's stock-filter path is approximate by design and labelled so in its log.

## 7. Files

| File | What it is |
|---|---|
| `obs/tools/render_matched.py` (dev copy in `scripts/`) | Revised pipeline: matcher maths + min-window limiter + lander |
| `obs/tools/report_card.py` (dev copy in `scripts/`) | 15-band profile + ebur128 meter, matcher-identical |
| `obs/tools/make_test_wavs.py` (dev copy in `scripts/`) | Synthetic speech-like take generator |
| `obs/tools/parity_check.sh` | C-vs-oracle parity harness (ALL PASS) |
| `obs/blueprints/*.json|md` | Revised blueprints v0.3 |
| `obs/plugin/` | OBS plugin source (template build system + vmcore) |
| `obs/script/` | `voice_match.py`, `isolate_voice.lua` |
| `obs/validation/REPORT.md` | This file |
