#!/usr/bin/env python3
"""Report card: measure any WAV with the exact matcher analysis (24 kHz, 2048
Hann, reservoir 240, gate, 15-band profile, P70/P90-P20) plus ffmpeg ebur128
integrated loudness / true peak. Prints JSON.

Usage: report_card.py WAV [WAV ...]
"""
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

ANALYSIS_RATE = 24000
FFT_SIZE = 2048
STEP = 4096
MAX_FRAMES = 240
BANDS = (100, 140, 200, 280, 400, 560, 800, 1120, 1600, 2240, 3200, 4480, 6400, 9000, 10900)


def percentile(sorted_values, fraction):
    index = (len(sorted_values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def run(args):
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode()[-500:])
    return result


def ebur128(path):
    """ffmpeg loudnorm print: integrated, true peak, LRA (dual-mono off; our
    files are stereo; for mono we still report as-is, matching matcher)."""
    out = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path),
               "-af", "loudnorm=I=-16:TP=-2:LRA=11:print_format=json", "-f", "null", "-"])
    log = out.stderr.decode("utf-8", "replace")
    start = log.rfind("\n{")
    data, _ = json.JSONDecoder().raw_decode(log[start + 1:])
    return {"loudness": float(data["input_i"]), "truePeak": float(data["input_tp"]),
            "loudnessRange": float(data["input_lra"])}


def read_float_frames(path, channels):
    """Decode whole file to f32le via ffmpeg, then cut 2048-sample frames with
    step 4096 the same way matcher's streaming read does (chunk = STEP*ch*4
    bytes, frame = first FFT_SIZE samples of each chunk)."""
    raw = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-ar", str(ANALYSIS_RATE),
               "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]).stdout
    rng = random.Random(16)
    frames = []
    count = 0
    offset = 0
    need = STEP * channels * 4
    while True:
        chunk = raw[offset:offset + need]
        offset += need
        if len(chunk) < FFT_SIZE * channels * 4:
            break
        samples = array("f")
        samples.frombytes(chunk[:FFT_SIZE * channels * 4])
        energy = sum(v * v for v in samples) / len(samples)
        rms = 10 * math.log10(max(energy, 1e-12))
        count += 1
        if len(frames) < MAX_FRAMES:
            frames.append((rms, samples))
        else:
            slot = rng.randrange(count)
            if slot < MAX_FRAMES:
                frames[slot] = (rms, samples)
    if not frames:
        raise RuntimeError("no frames")
    levels = sorted(level for level, _ in frames)
    gate = max(-65, percentile(levels, 0.90) - 18, percentile(levels, 0.99) - 27)
    selected = [(l, s) for l, s in frames if l >= gate]
    if len(selected) < 4:
        raise RuntimeError("too little speech")
    return selected


def spectrum(samples, offset, channels, setup):
    reversed_bits, window, steps = setup
    values = [samples[index * channels + offset] * window[index] for index in reversed_bits]
    for size, rotations in steps:
        half = size // 2
        for start in range(0, FFT_SIZE, size):
            for move, rotation in enumerate(rotations):
                low, high = start + move, start + move + half
                even, odd = values[low], values[high] * rotation
                values[low], values[high] = even + odd, even - odd
    return values[:FFT_SIZE // 2 + 1]


def fft_setup():
    bit_count = FFT_SIZE.bit_length() - 1
    reversed_bits = [int(f"{index:0{bit_count}b}"[::-1], 2) for index in range(FFT_SIZE)]
    window = [0.5 - 0.5 * math.cos(math.tau * index / (FFT_SIZE - 1)) for index in range(FFT_SIZE)]
    steps = []
    size = 2
    while size <= FFT_SIZE:
        steps.append((size, [complex(math.cos(math.tau * i / size), -math.sin(math.tau * i / size))
                             for i in range(size // 2)]))
        size *= 2
    return reversed_bits, window, steps


def profile(path):
    info = run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                "stream=channels,sample_rate", "-of", "json", str(path)])
    channels = int(json.loads(info.stdout)["streams"][0]["channels"])
    frames = read_float_frames(path, channels)
    setup = fft_setup()
    bins_per_hz = FFT_SIZE / ANALYSIS_RATE
    band_edges = [BANDS[0] / math.sqrt(1.4)]
    band_edges += [math.sqrt(low * high) for low, high in zip(BANDS, BANDS[1:])]
    band_edges.append(11900)
    buckets = [range(math.ceil(low * bins_per_hz), math.ceil(high * bins_per_hz))
               for low, high in zip(band_edges, band_edges[1:])]
    sums = [0.0] * len(BANDS)
    for _, samples in frames:
        band_energy = [0.0] * len(BANDS)
        for channel in range(channels):
            bins = spectrum(samples, channel, channels, setup)
            for index, bucket in enumerate(buckets):
                band_energy[index] += sum(bins[b].real ** 2 + bins[b].imag ** 2 for b in bucket)
        total = max(1e-12, sum(band_energy))
        for index, power in enumerate(band_energy):
            sums[index] += power / total
    spectrum_db = [10 * math.log10(max(p / len(frames), 1e-10)) for p in sums]
    speech = sorted(level for level, _ in frames)
    return {"spectrumDb": [round(v, 3) for v in spectrum_db],
            "speechRms70": round(percentile(speech, 0.70), 2),
            "speechSpread": round(percentile(speech, 0.90) - percentile(speech, 0.20), 2)}


def measure(path):
    path = Path(path)
    values = ebur128(path)
    values.update(profile(path))
    values["sampleRate"] = int(json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate", "-of", "json", path]).stdout)["streams"][0]["sample_rate"])
    return values


def main():
    print(json.dumps({str(Path(p).name): measure(p) for p in sys.argv[1:]}, indent=2))


if __name__ == "__main__":
    main()
