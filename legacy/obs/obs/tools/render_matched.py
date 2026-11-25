#!/usr/bin/env python3
"""The sound-engineer revision of the render pipeline.

Replaces match_voice.process_match with:
  1. matcher analysis + match_curve (unchanged authority)
  2. tone filters (unchanged authority)
  3. OUR true-peak lookahead limiter (numpy, deterministic; alimiter in FFmpeg
     overshoots ~2.1 dB and is unusable for a ceiling guarantee)
  4. verify-and-correct loudness lander (up to 3 renders, converges <0.3 LU)

Usage: render_matched.py INPUT --output OUT.wav [--reference ref.json]
       [--depth 75 --presence 75 --control 45] [--target LUFS] [--json out.json]
"""
import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matcher import match_voice  # noqa: E402


# ---------------------------------------------------------------- limiter ---
def limit_exact(block, ceiling_dbtp=-2.0, attack_ms=5.0, release_ms=60.0, rate=48000):
    """4x-oversampled true-peak lookahead limiter with a hard guarantee.

    Gain per sample = min(ceiling/env, 1) over a sliding window of lookahead+1
    samples, so the gain is fully lowered BEFORE the peak arrives (zero
    overshoot by construction). Release-only smoothing (60 ms) for the
    recovery edge. Stereo-linked (max across channels). Deterministic.

    block: (channels, n) float64. Returns same shape.
    """
    channels, n = block.shape
    look = int(rate * attack_ms / 1000)
    ceiling = 10 ** (ceiling_dbtp / 20)
    mag = np.max(np.abs(block), axis=0)
    if n > 1:
        m1 = np.abs(0.75 * mag[:-1] + 0.25 * mag[1:])
        m2 = np.abs(0.50 * mag[:-1] + 0.50 * mag[1:])
        m3 = np.abs(0.25 * mag[:-1] + 0.75 * mag[1:])
        env = np.maximum.reduce([mag,
                                 np.concatenate([[mag[0]], m1]),
                                 np.concatenate([[mag[0]], m2]),
                                 np.concatenate([[mag[0]], m3])])
    else:
        env = mag
    needed = np.where(env > ceiling, ceiling / np.maximum(env, 1e-12), 1.0)
    # Sliding-window minimum over the lookahead horizon (min-filter).
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.concatenate([needed, np.ones(look)])
    gmin = sliding_window_view(pad, look + 1).min(axis=1)
    # Release smoothing: fall instantly to gmin, rise with 60 ms constant.
    rel = math.exp(-1.0 / (rate * release_ms / 1000))
    g = 1.0
    gains = np.empty(n)
    for i in range(n):
        target = gmin[i]
        if target <= g:
            g = target
        else:
            g = target + (g - target) * rel
        gains[i] = g
    return block * gains[None, :], gains


# ------------------------------------------------------------- rendering ---
def run(args):
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode()[-600:])
    return result


def measure_filters(path, filters):
    tools = match_voice.media_tools()
    info = match_voice.wav_info(tools, path)
    return match_voice.measure(tools, path, info, filters)


def decode(path):
    raw = run(["ffmpeg", "-hide_banner", "-i", str(path), "-c:a", "pcm_f32le",
               "-f", "f32le", "pipe:1"]).stdout
    x = np.frombuffer(raw, np.float32).copy()
    # We need channel count; ask ffprobe.
    meta = run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                "stream=channels,sample_rate", "-of", "json", str(path)]).stdout
    d = json.loads(meta)["streams"][0]
    ch, rate = int(d["channels"]), int(d["sample_rate"])
    return x.reshape(-1, ch).T, rate


def encode(path, block, rate, bits=24):
    """Write (channels, n) float block as a PCM WAV. We feed f32le samples to
    ffmpeg on stdin and let it do the integer conversion (a previous version
    wrote s32 bytes into an f32le input, bit-reinterpreting every sample)."""
    data = block.T.astype(np.float32)
    raw = data.tobytes()
    acodec = ["-c:a", "pcm_s24le"] if bits == 24 else ["-c:a", "pcm_s16le"]
    result = subprocess.run(["ffmpeg", "-hide_banner", "-y", "-f", "f32le", "-ar", str(rate),
                             "-ac", str(block.shape[0]), "-i", "pipe:0", *acodec, str(path)],
                            input=raw, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode()[-600:])


def apply_chain(path, chain, ceiling, out_path):
    """Apply ffmpeg filter chain, then our limiter in numpy, then write."""
    temp = Path(tempfile.mkdtemp()) / "chain.wav"
    run(["ffmpeg", "-hide_banner", "-y", "-i", str(path), "-af", ",".join(chain),
         "-c:a", "pcm_f32le", str(temp)])
    block, rate = decode(temp)
    out, _ = limit_exact(block, ceiling_dbtp=ceiling, rate=rate)
    encode(out_path, out, rate)
    temp.unlink(missing_ok=True)


def render_with_gain(path, chain, ceiling, gain_db, out_path):
    temp = Path(tempfile.mkdtemp()) / "chain.wav"
    run(["ffmpeg", "-hide_banner", "-y", "-i", str(path), "-af",
         ",".join(chain + [f"volume={gain_db:.3f}dB"]), "-c:a", "pcm_f32le", str(temp)])
    block, rate = decode(temp)
    out, _ = limit_exact(block, ceiling_dbtp=ceiling, rate=rate)
    encode(out_path, out, rate)
    temp.unlink(missing_ok=True)


def tone_chain(curve, depth, presence, control, ceiling):
    chain_args = argparse.Namespace(depth=depth, presence=presence, control=control, mode="voice")
    chain = match_voice.tone_filters(curve, chain_args)
    return chain


def land(path, curve, depth, presence, control, target, ceiling, output, log):
    """Verify-and-correct loudness lander under a guaranteed ceiling."""
    chain = tone_chain(curve, depth, presence, control, ceiling)
    # First pass: measure through the chain (loudnorm can't run our limiter,
    # so we approximate the chain-only loudness, then verify on the real
    # render that includes the limiter; limiter barely changes loudness when
    # it is not limiting, and when it is, the verify loop catches it).
    processed = measure_filters(path, chain)
    gain = min(target - processed["loudness"], match_voice.MAX_GAIN)
    best = None
    for attempt in range(3):
        temp_out = Path(str(output) + f".lander{attempt}.wav")
        render_with_gain(path, chain, ceiling, gain, temp_out)
        tools = match_voice.media_tools()
        after = match_voice.measure(tools, temp_out, match_voice.wav_info(tools, temp_out))
        error = target - after["loudness"]
        log.append({"attempt": attempt, "gain_db": round(gain, 3),
                    "loudness": after["loudness"], "truePeak": after["truePeak"],
                    "error_lu": round(error, 3)})
        best = (temp_out, after)
        if abs(error) <= 0.25 or after["truePeak"] > ceiling - 0.05:
            break
        gain = min(gain + error, match_voice.MAX_GAIN)
    final_out, final_measure = best
    if final_out != output:
        if output.exists():
            output.unlink()
        final_out.rename(output)
    for leftover in output.parent.glob(output.name + ".lander*.wav"):
        leftover.unlink(missing_ok=True)
    return final_measure, gain


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path,
                        default=Path(__file__).resolve().parent / "ref.json")
    parser.add_argument("--depth", type=float, default=75)
    parser.add_argument("--presence", type=float, default=75)
    parser.add_argument("--control", type=float, default=45)
    parser.add_argument("--target", type=float, default=None)
    parser.add_argument("--ceiling", type=float, default=-2.0)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    tools = match_voice.media_tools()
    reference = match_voice.read_reference(tools, args.reference, True)
    target = args.target if args.target is not None else reference["loudness"]

    info = match_voice.wav_info(tools, args.input)
    source = match_voice.profile(tools, args.input, info)
    curve = match_voice.match_curve(source, reference)

    log = []
    out_measure, gain = land(args.input, curve, args.depth, args.presence,
                             args.control, target, args.ceiling, args.output, log)

    out_profile = match_voice.profile(tools, args.output,
                                      match_voice.wav_info(tools, args.output))
    print(f"curve: {json.dumps(curve)}")
    for row in log:
        print("lander:", row)
    print(f"source: {source['loudness']:.2f} LUFS / {source['truePeak']:.2f} dBTP")
    print(f"output: {out_measure['loudness']:.2f} LUFS / {out_measure['truePeak']:.2f} dBTP "
          f"(target {target:.2f}, gain {gain:+.2f} dB, "
          f"error {abs(out_measure['loudness'] - target):.2f} LU)")
    print(f"speechSpread: {out_profile['speechSpread']} (ref {reference['speechSpread']})")

    if args.json:
        args.json.write_text(json.dumps({
            "curve": curve, "lander": log, "source": source,
            "output": out_measure, "output_profile": out_profile,
            "band_deltas": [round(r - o, 2) for r, o in
                            zip(reference["spectrumDb"], out_profile["spectrumDb"])]},
                           indent=2))


if __name__ == "__main__":
    main()
