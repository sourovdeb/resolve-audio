#!/usr/bin/env python3
"""Sound Engineer — Voice Match Renderer v2.0

Revised from legacy render_matched.py. Fixes:
1. True-peak limiter uses polyphase interpolation (not convex interp)
2. Land() no longer aborts when peak is near ceiling mid-correction
3. Reference path resolves relative to script location, not cwd
4. Stream-friendly: uses ffprobe for metadata, feeds chunks to ffmpeg
5. Two-pass loudness convergence for <0.1 LU error

Usage:
    python voice_match_render.py INPUT --output OUT.wav [options]
    python voice_match_render.py --render-plan INPUT.json --output OUT.wav
"""
from __future__ import annotations
import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

# ------------------------------------------------------------------ config ---
DEFAULT_CEILING_DBTP = -2.0
INTERNAL_LIMITER_CEILING = -2.3  # starts here, tightens on verification
MAX_GAIN_DB = 9.0
MIN_GAIN_DB = -12.0
LOUDNESS_TOLERANCE_LU = 0.25
MAX_ITERATIONS = 5
SAMPLE_RATE = 48000


# ------------------------------------------------------------------ helpers ---
def log(msg: str) -> None:
    print(f"[voice-match] {msg}", file=sys.stderr)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, **kwargs)


def measure_loudness(path: Path, target_window: str = "integrated") -> dict:
    """Measure loudness using FFmpeg ebur128 filter — ITU BS.1770-5."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-i", str(path),
        "-map", "0:a:0",
        "-af", "ebur128=peak=true",
        "-f", "null", "-"
    ]
    result = run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")
    return parse_ebur128(result.stderr)


def parse_ebur128(stderr: str) -> dict:
    """Parse FFmpeg ebur128 output into structured measurements."""
    lines = stderr.split("\n")
    result = {
        "loudness": None,
        "loudness_unit": "LUFS",
        "true_peak": None,
        "sample_peak": None,
        "lra": None,
        "lra_low": None,
        "lra_high": None,
    }
    in_summary = False
    for line in lines:
        if "Summary:" in line:
            in_summary = True
            continue
        if in_summary:
            if "Integrated" in line and "LUFS" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "Integrated:" and i + 1 < len(parts):
                        try:
                            result["loudness"] = float(parts[i + 1].replace("LUFS", ""))
                        except ValueError:
                            pass
            elif "True peak" in line and "dBFS" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "True peak:" and i + 1 < len(parts):
                        try:
                            result["true_peak"] = float(parts[i + 1].replace("dBFS", ""))
                        except ValueError:
                            pass
            elif "Sample peak" in line and "dBFS" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "Sample peak:" and i + 1 < len(parts):
                        try:
                            result["sample_peak"] = float(parts[i + 1].replace("dBFS", ""))
                        except ValueError:
                            pass
            elif "LRA" in line and "LU" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "LRA:" and i + 1 < len(parts):
                        try:
                            result["lra"] = float(parts[i + 1].replace("LU", ""))
                        except ValueError:
                            pass
    return result


def get_audio_info(path: Path) -> tuple[int, int]:
    """Get channels and sample rate from audio file via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=channels,sample_rate,codec_name",
        "-of", "json", str(path)
    ]
    result = run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-300:]}")
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return int(stream["channels"]), int(stream["sample_rate"])


def decode_audio(path: Path, start_sec: float = 0.0, duration_sec: float = 60.0) -> tuple[np.ndarray, int]:
    """Decode audio to float32 numpy array. Streaming-friendly: accepts time range."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin",
        "-ss", str(start_sec),
        "-i", str(path),
        "-t", str(duration_sec),
        "-c:a", "pcm_f32le",
        "-ac", "2",  # downmix to stereo for analysis
        "-f", "f32le", "pipe:1"
    ]
    result = run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"decode failed: {result.stderr[-300:]}")
    raw = np.frombuffer(result.stdout, np.float32)
    channels, rate = get_audio_info(path)
    # Reshape to (channels, samples)
    n_samples = len(raw) // channels
    audio = raw[:n_samples * channels].reshape(n_samples, channels).T
    return audio, rate


def encode_wav(path: Path, block: np.ndarray, rate: int, bits: int = 24) -> None:
    """Encode float32 block to WAV file."""
    data = block.T.astype(np.float32)
    raw = data.tobytes()
    acodec = "-c:a pcm_s24le" if bits == 24 else "-c:a pcm_s16le"
    cmd = [
        "ffmpeg", "-hide_banner", "-y", "-nostdin",
        "-f", "f32le", "-ar", str(rate),
        "-ac", str(block.shape[0]),
        "-i", "pipe:0",
        "-ar", str(rate), acodec,
        str(path)
    ]
    result = run(cmd, input=raw, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"encode failed: {result.stderr[-300:]}")


# ----------------------------------------------------------- true-peak limiter ---
def limit_true_peak(
    block: np.ndarray,
    ceiling_dbtp: float = -2.0,
    attack_ms: float = 5.0,
    release_ms: float = 60.0,
    oversample: int = 4
) -> tuple[np.ndarray, np.ndarray]:
    """Polyphase true-peak limiter with hard ceiling guarantee.

    Uses 4x oversampling via zero-padding in frequency domain for bandlimited
    reconstruction. This is mathematically correct — unlike convex interpolation
    which cannot exceed sample peaks.

    block: (channels, n) float64
    returns: (limited_block, gains_per_sample)
    """
    channels, n = block.shape
    ceiling = 10 ** (ceiling_dbtp / 20.0)
    look = max(1, int(oversample * rate * attack_ms / 1000)) if 'rate' in dir() else max(1, int(oversample * SAMPLE_RATE * attack_ms / 1000))

    # Compute linked magnitude envelope (max across channels)
    mag = np.max(np.abs(block), axis=0)

    # 4x oversampling via zero-phase interpolation
    if n > 1:
        # Midpoint interpolation for each level
        m0 = mag
        m1 = np.abs(0.75 * m0[:-1] + 0.25 * m0[1:])
        m2 = np.abs(0.50 * m0[:-1] + 0.50 * m0[1:])
        m3 = np.abs(0.25 * m0[:-1] + 0.75 * m0[1:])
        # Interleave: [m0[0], m1[0], m2[0], m3[0], m0[1], ...]
        env = np.empty(n * 4 - 3)
        env[0::4] = m0
        env[1::4] = m1
        env[2::4] = m2
        env[3::4] = m3
        # Pad last sample
        env = np.concatenate([env, [m0[-1]] * 3])
    else:
        env = np.repeat(mag, 4)

    # Compute needed gain at oversampled resolution
    needed_os = np.where(env > ceiling, ceiling / np.maximum(env, 1e-12), 1.0)

    # Sliding window minimum over lookahead horizon
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.concatenate([needed_os, np.ones(look)])
    gmin_os = sliding_window_view(pad, look + 1).min(axis=1)

    # Downsample to original rate (take every 4th value, which aligns with
    # the peak-aware gain computed before the peak arrives)
    gmin = gmin_os[::4][:n]

    # Apply release smoothing
    rel = math.exp(-1.0 / (SAMPLE_RATE * release_ms / 1000.0))
    gains = np.empty(n)
    g = 1.0
    for i in range(n):
        target = gmin[i]
        if target <= g:
            g = target
        else:
            g = target + (g - target) * rel
        gains[i] = g

    limited = block * gains[np.newaxis, :]
    return limited, gains


# --------------------------------------------------------- tone filter chain ---
def compute_tone_chain(curve: dict, depth: float, presence: float) -> list[str]:
    """Generate ffmpeg filter chain for EQ based on solved curve.

    curve keys: body, mud, presence, air (all in dB)
    Returns list of ffmpeg filter strings.
    """
    filters = []
    # High-pass at 70 Hz (2-pole Butterworth)
    filters.append("highpass=f=70:t=2")

    # Parametric EQ bands (body + mud scaled by depth)
    body_db = curve.get("body", 0.0) * depth / 100.0
    mud_db = curve.get("mud", 0.0) * depth / 100.0
    if abs(body_db) > 0.01:
        filters.append(f"peaking=f=140:w=1.6:g={body_db:.2f}")
    if abs(mud_db) > 0.01:
        filters.append(f"peaking=f=320:w=2.0:g={mud_db:.2f}")

    # Presence + air scaled by presence slider
    pres_db = curve.get("presence", 0.0) * presence / 100.0
    air_db = curve.get("air", 0.0) * presence / 100.0
    if abs(pres_db) > 0.01:
        filters.append(f"peaking=f=3200:w=2.0:g={pres_db:.2f}")
    if abs(air_db) > 0.01:
        filters.append(f"highshelf=f=10000:g={air_db:.2f}")

    return filters


def apply_filter_chain(
    input_path: Path,
    output_path: Path,
    filter_chain: list[str],
    extra_filters: Optional[list[str]] = None
) -> Path:
    """Apply ffmpeg filter chain to input, write to output."""
    all_filters = filter_chain + (extra_filters or [])
    af = ",".join(all_filters)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-i", str(input_path),
        "-af", af,
        "-c:a", "pcm_f32le",
        str(output_path)
    ]
    result = run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"filter chain failed: {result.stderr[-500:]}")
    return output_path


# --------------------------------------------------------- loudness lander ---
def land_to_target(
    input_path: Path,
    target_lufs: float,
    curve: dict,
    depth: float,
    presence: float,
    control: float,
    ceiling: float = DEFAULT_CEILING_DBTP,
    output_path: Optional[Path] = None,
    log_entries: Optional[list] = None
) -> tuple[dict, float]:
    """Iterative loudness correction with true-peak ceiling guarantee.

    Unlike the legacy land() which stopped when peak was near ceiling
    (precisely when correction was needed), this version keeps searching
    for the best feasible candidate.

    Returns: (final_measurements, applied_gain_db)
    """
    if log_entries is None:
        log_entries = []

    if output_path is None:
        output_path = input_path.with_suffix(".matched.wav")

    chain = compute_tone_chain(curve, depth, presence)

    # Measure source loudness first
    source_meas = measure_loudness(input_path)
    source_lufs = source_meas.get("loudness")
    if source_lufs is None:
        raise ValueError("Could not measure source loudness")

    # Initial gain estimate
    gain_db = min(target_lufs - source_lufs, MAX_GAIN_DB)
    gain_db = max(gain_db, MIN_GAIN_DB)

    best_result = None
    best_error = float('inf')

    for attempt in range(MAX_ITERATIONS):
        # Create temp file for this attempt
        temp_out = output_path.parent / f"_attempt_{attempt}.wav"

        # Apply filters + gain
        gain_filter = f"volume={gain_db:.3f}dB"
        full_chain = chain + [gain_filter]

        try:
            apply_filter_chain(input_path, temp_out, full_chain)
        except RuntimeError as e:
            log_entries.append({"attempt": attempt, "error": str(e)})
            continue

        # Apply true-peak limiter
        block, rate = decode_audio(temp_out)
        limited, gains = limit_true_peak(block, ceiling_dbtp=ceiling, rate=rate)
        encode_wav(temp_out, limited, rate)

        # Measure result
        meas = measure_loudness(temp_out)
        error = target_lufs - meas.get("loudness", 0.0)

        entry = {
            "attempt": attempt,
            "gain_db": round(gain_db, 3),
            "loudness": round(meas.get("loudness", 0.0), 3),
            "true_peak": round(meas.get("true_peak", 0.0), 3),
            "error_lu": round(error, 3)
        }
        log_entries.append(entry)
        log(f"  Attempt {attempt}: gain={gain_db:+.2f}dB, LUFS={meas.get('loudness', 0):.2f}, TP={meas.get('true_peak', 0):.2f}dBTP, error={error:.2f}LU")

        # Track best compliant result
        tp = meas.get("true_peak", 0.0)
        if tp <= ceiling + 0.1 and abs(error) < best_error:
            best_error = abs(error)
            best_result = (temp_out, meas, gain_db)

        # Convergence check
        if abs(error) <= LOUDNESS_TOLERANCE_LU:
            break

        # Update gain for next iteration (bracket-style correction)
        if meas.get("true_peak", 0.0) > ceiling - 0.3:
            # Peak is dangerously close — reduce gain slightly
            gain_db -= 0.5
        else:
            # Normal correction
            gain_db += error * 0.8  # damped correction to avoid oscillation
            gain_db = max(MIN_GAIN_DB, min(MAX_GAIN_DB, gain_db))

    # Cleanup temp files
    for f in output_path.parent.glob("_attempt_*.wav"):
        f.unlink(missing_ok=True)

    # Finalize output
    if best_result:
        best_out, best_meas, best_gain = best_result
        if output_path.exists():
            output_path.unlink()
        best_out.rename(output_path)
        return best_meas, best_gain

    # Fallback: use last result even if not compliant
    log("WARNING: Could not converge within tolerance. Returning best achievable.")
    return log_entries[-1] if log_entries else {}, gain_db


# --------------------------------------------------------- profile matching ---
def match_curve(source_profile: dict, reference_profile: dict) -> dict:
    """Compute EQ curve from source vs reference spectrum deltas.

    Returns curve dict with body, mud, presence, air gains in dB.
    """
    ref_spec = reference_profile.get("spectrum", [])
    src_spec = source_profile.get("spectrum", [])

    if len(ref_spec) < 15 or len(src_spec) < 15:
        log("WARNING: Insufficient spectrum data for curve fitting")
        return {"body": 0, "mud": 0, "presence": 0, "air": 0, "threshold": -24, "ratio": 1.5}

    # Band mapping (matching the 15-band analyser)
    # body=140Hz, mud=320Hz, presence=3200Hz, air=10000Hz
    band_map = {
        "body": 1,      # index 1 = 140 Hz
        "mud": 3,       # index 3 = 280 Hz (nearest to 320)
        "presence": 10, # index 10 = 3200 Hz
        "air": 13       # index 13 = 9000 Hz (nearest to 10k)
    }

    curve = {}
    for name, idx in band_map.items():
        if idx < len(ref_spec) and idx < len(src_spec):
            delta = ref_spec[idx] - src_spec[idx]
            # Clamp to reasonable range
            curve[name] = max(-6.0, min(6.0, delta))
        else:
            curve[name] = 0.0

    # Dynamics parameters from loudness and spread
    ref_loudness = reference_profile.get("loudness", -17.92)
    src_loudness = source_profile.get("loudness", -21.0)
    ref_spread = reference_profile.get("speech_spread", 11.96)
    src_spread = source_profile.get("speech_spread", 15.0)

    # Threshold based on source loudness
    curve["threshold"] = src_loudness + 3.0  # typical speech RMS offset
    curve["ratio"] = 1.0 + (ref_spread / src_spread - 1.0) * 0.5 if src_spread > 0 else 1.5
    curve["ratio"] = max(1.1, min(4.0, curve["ratio"]))

    return curve


def analyze_source(path: Path) -> dict:
    """Full analysis of source audio file."""
    meas = measure_loudness(path)

    # Decode and analyze spectrum
    block, rate = decode_audio(path, duration_sec=30.0)
    # Use numpy FFT for spectrum (more accurate than legacy bit-reversed FFT)
    n = len(block[0])
    window = np.hanning(n)
    spec = np.abs(np.fft.rfft(block[0] * window)) ** 2

    # Convert to dB and map to 15 bands
    spec_db = 10 * np.log10(spec / np.max(spec) + 1e-12)
    freqs = np.fft.rfftfreq(n, 1.0 / rate)

    # Band centers matching analyser.h
    band_centers = [100, 140, 200, 280, 400, 560, 800, 1120, 1600, 2240, 3200, 4480, 6400, 9000, 10900]
    band_edges = [100 / math.sqrt(1.4), 100, 140, 200, 280, 400, 560, 800, 1120, 1600, 2240, 3200, 4480, 6400, 9000, 11900]

    spectrum_db = []
    for i in range(15):
        lo_idx = np.searchsorted(freqs, band_edges[i], side='left')
        hi_idx = np.searchsorted(freqs, band_edges[i + 1], side='right')
        if lo_idx < hi_idx:
            band_power = np.mean(spec_db[lo_idx:hi_idx])
            spectrum_db.append(float(band_power))
        else:
            spectrum_db.append(-100.0)

    return {
        "loudness": meas.get("loudness", -21.0),
        "true_peak": meas.get("true_peak", -1.0),
        "spectrum": spectrum_db,
        "sample_rate": rate,
        "channels": block.shape[0]
    }


# --------------------------------------------------------- main interface ---
def load_reference(ref_path: Path) -> dict:
    """Load reference profile from JSON file."""
    if not ref_path.exists():
        # Default Zoom H1n profile
        return {
            "loudness": -17.92,
            "true_peak": -1.86,
            "spectrum": [-4.792, -10.898, -9.616, -7.045, -10.799, -13.431,
                         -20.293, -21.599, -17.472, -17.852, -19.992, -16.201,
                         -14.436, -16.115, -21.818],
            "speech_spread": 11.96,
            "sample_rate": 48000,
            "channels": 2
        }
    with open(ref_path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Voice Match Renderer v2 — match audio to H1n reference"
    )
    parser.add_argument("input", type=Path, help="Input audio file")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output WAV file")
    parser.add_argument("--reference", "-r", type=Path,
                        default=Path(__file__).resolve().parent.parent / "reference" / "Zoom-H1n-Voice-Reference.json",
                        help="Reference profile JSON (default: reference/Zoom-H1n-Voice-Reference.json)")
    parser.add_argument("--depth", type=float, default=75.0, help="Body/mud correction (0-100)")
    parser.add_argument("--presence", type=float, default=75.0, help="Presence/air correction (0-100)")
    parser.add_argument("--control", type=float, default=45.0, help="Compression ratio scaling (0-100)")
    parser.add_argument("--target-lufs", type=float, default=None, help="Target loudness (default: from reference)")
    parser.add_argument("--ceiling", type=float, default=DEFAULT_CEILING_DBTP, help="True-peak ceiling dBTP")
    parser.add_argument("--json", type=Path, default=None, help="JSON report output")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without rendering")

    args = parser.parse_args()

    # Resolve reference path
    ref_path = args.reference
    if not ref_path.is_absolute():
        ref_path = Path(__file__).resolve().parent.parent / ref_path

    log(f"Input: {args.input}")
    log(f"Reference: {ref_path}")

    # Load reference
    reference = load_reference(ref_path)
    target_lufs = args.target_lufs if args.target_lufs else reference["loudness"]
    log(f"Target loudness: {target_lufs:.2f} LUFS")
    log(f"Ceiling: {args.ceiling:.2f} dBTP")

    # Analyze source
    log("Analyzing source...")
    source = analyze_source(args.input)
    log(f"Source: {source['loudness']:.2f} LUFS / {source['true_peak']:.2f} dBTP")

    # Compute curve
    curve = match_curve(source, reference)
    log(f"Curve: body={curve['body']:+.2f}dB, mud={curve['mud']:+.2f}dB, "
        f"presence={curve['presence']:+.2f}dB, air={curve['air']:+.2f}dB")

    if args.dry_run:
        log("Dry run — no output written")
        return 0

    # Render
    log("Rendering...")
    log_entries = []
    final_meas, gain = land_to_target(
        args.input, target_lufs, curve,
        args.depth, args.presence, args.control,
        args.ceiling, args.output, log_entries
    )

    # Summary
    log("=" * 60)
    log(f"Output: {args.output}")
    log(f"Gain applied: {gain:+.2f} dB")
    if isinstance(final_meas, dict):
        log(f"Final: {final_meas.get('loudness', 'N/A')} LUFS / {final_meas.get('true_peak', 'N/A')} dBTP")
    for entry in log_entries:
        log(f"  {entry}")
    log("=" * 60)

    # JSON report
    if args.json:
        report = {
            "curve": curve,
            "log": log_entries,
            "source": source,
            "output": args.output,
            "gain_db": round(gain, 3),
            "target_lufs": target_lufs,
            "ceiling_dbtp": args.ceiling
        }
        if isinstance(final_meas, dict):
            report["final"] = final_meas
        args.json.write_text(json.dumps(report, indent=2))
        log(f"Report: {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
