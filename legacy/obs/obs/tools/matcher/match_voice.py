#!/usr/bin/env python3
"""Measure and match speech WAVs with Python 3.9+ and FFmpeg. Runs locally."""

import argparse
from array import array
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile


ANALYSIS_RATE = 24000
FFT_SIZE = 2048
STEP = 4096
MAX_FRAMES = 240
BANDS = (100, 140, 200, 280, 400, 560, 800, 1120, 1600, 2240, 3200, 4480, 6400, 9000, 10900)
FILTERS = (("body", 140, 0.8, 4.5), ("mud", 320, 1.0, 4.5),
           ("presence", 3200, 1.0, 4.5), ("air", 10000, 0.7, 2.5))
CEILING = -2.0
MAX_GAIN = 9.0
REFERENCE_TYPE = "voice-macro-reference"
PLAN_TYPE = "voice-macro-track-match"


def limit(value, low, high):
    return min(high, max(low, value))


def percentile(sorted_values, fraction):
    index = (len(sorted_values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def media_tools():
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ValueError("Install FFmpeg with ffprobe, then reopen the terminal or Resolve.")
    return ffmpeg, ffprobe


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(detail[-1] if detail else "FFmpeg could not read or process the file.")
    return result


def wav_info(tools, path):
    if path.suffix.lower() != ".wav" or not path.is_file():
        raise ValueError("Choose an existing WAV file.")
    result = run([tools[1], "-v", "error", "-select_streams", "a:0", "-show_entries",
                  "stream=channels,sample_rate,duration_ts,time_base,duration", "-of", "json", str(path)])
    try:
        stream, = json.loads(result.stdout)["streams"]
        frames = int(stream["duration_ts"])
        rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        duration = float(stream["duration"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Could not read the WAV duration or format.") from exc
    if channels not in (1, 2) or not 8000 <= rate <= 192000:
        raise ValueError("Use a mono or stereo WAV at 8–192 kHz.")
    if stream.get("time_base") != "1/" + str(rate) or frames < rate or duration < 1:
        raise ValueError("Use at least one second of WAV audio.")
    return {"rate": rate, "channels": channels, "frames": frames, "duration": duration}


def ffmpeg_input(tools, path, loglevel="error"):
    return [tools[0], "-hide_banner", "-nostdin", "-loglevel", loglevel,
            "-i", str(path), "-map", "0:a:0"]


def measure(tools, path, info, filters=()):
    dual_mono = "true" if info["channels"] == 1 else "false"
    meter = "loudnorm=I=-16:TP=-2:LRA=11:dual_mono=" + dual_mono + ":print_format=json"
    result = run(ffmpeg_input(tools, path, "info") +
                 ["-af", ",".join([*filters, meter]), "-f", "null", "-"])
    log = result.stderr.decode("utf-8", "replace")
    start = log.rfind("\n{")
    if start < 0:
        raise ValueError("Your FFmpeg build did not return loudness measurements.")
    try:
        data, _ = json.JSONDecoder().raw_decode(log[start + 1:])
        result = {"loudness": float(data["input_i"]), "truePeak": float(data["input_tp"]),
                  "loudnessRange": float(data["input_lra"])}
    except (KeyError, ValueError) as exc:
        raise ValueError("Could not read loudness measurements.") from exc
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("The WAV is silent or too quiet to measure. Choose audible speech.")
    return result


def fft_setup():
    bit_count = FFT_SIZE.bit_length() - 1
    reversed_bits = [int(f"{index:0{bit_count}b}"[::-1], 2) for index in range(FFT_SIZE)]
    window = [0.5 - 0.5 * math.cos(math.tau * index / (FFT_SIZE - 1)) for index in range(FFT_SIZE)]
    steps = []
    size = 2
    while size <= FFT_SIZE:
        steps.append((size, [complex(math.cos(math.tau * index / size), -math.sin(math.tau * index / size))
                             for index in range(size // 2)]))
        size *= 2
    return reversed_bits, window, steps


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


def speech_frames(tools, path, info):
    channels = info["channels"]
    args = ffmpeg_input(tools, path) + ["-ar", str(ANALYSIS_RATE), "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]
    rng = random.Random(16)
    frames = []
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors)
        count = 0
        with process.stdout:
            while True:
                chunk = process.stdout.read(STEP * channels * 4)
                if len(chunk) < FFT_SIZE * channels * 4:
                    break
                samples = array("f")
                samples.frombytes(chunk[:FFT_SIZE * channels * 4])
                if sys.byteorder != "little":
                    samples.byteswap()
                energy = sum(value * value for value in samples) / len(samples)
                rms = 10 * math.log10(max(energy, 1e-12))
                count += 1
                if len(frames) < MAX_FRAMES:
                    frames.append((rms, samples))
                else:
                    slot = rng.randrange(count)
                    if slot < MAX_FRAMES:
                        frames[slot] = (rms, samples)
        if process.wait():
            errors.seek(0)
            raise ValueError("Could not decode WAV samples. " + errors.read(400).decode("utf-8", "replace"))
    if not frames:
        raise ValueError("Could not find audio frames.")
    levels = sorted(level for level, _ in frames)
    gate = max(-65, percentile(levels, 0.90) - 18, percentile(levels, 0.99) - 27)
    selected = [(level, samples) for level, samples in frames if level >= gate]
    if len(selected) < 4:
        raise ValueError("Too little speech-level audio. Choose a passage with more speech.")
    return selected


def profile(tools, path, info):
    levels = measure(tools, path, info)
    frames = speech_frames(tools, path, info)
    channels = info["channels"]
    setup = fft_setup()
    bins_per_hz = FFT_SIZE / ANALYSIS_RATE
    # Integrate power within adjacent bands. Average channels in power, never waveform.
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
    spectrum_db = [10 * math.log10(max(power / len(frames), 1e-10)) for power in sums]
    speech = sorted(level for level, _ in frames)
    return {"type": REFERENCE_TYPE, "schema": 1, "sampleRate": info["rate"], "bandsHz": list(BANDS),
            "spectrumDb": [round(value, 3) for value in spectrum_db], **levels,
            "speechRms70": round(percentile(speech, 0.70), 2),
            "speechSpread": round(percentile(speech, 0.90) - percentile(speech, 0.20), 2)}


def number(value, low, high):
    return type(value) in (int, float) and low <= value <= high


def read_reference(tools, path, include_spectrum):
    if path.suffix.lower() == ".json":
        if path.stat().st_size > 32768:
            raise ValueError("Reference profile exceeds its size limit.")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if (not isinstance(data, dict) or data.get("type") != REFERENCE_TYPE or data.get("schema") != 1
                or data.get("bandsHz") != list(BANDS)
                or not isinstance(data.get("spectrumDb"), list) or len(data["spectrumDb"]) != len(BANDS)
                or not all(number(value, -100, 0) for value in data["spectrumDb"])
                or not number(data.get("sampleRate"), 8000, 192000)
                or not number(data.get("loudness"), -70, 10)
                or not number(data.get("speechSpread"), 0, 120)):
            raise ValueError("Choose a reference WAV or a profile created by the profile command.")
        return data
    info = wav_info(tools, path)
    return profile(tools, path, info) if include_spectrum else measure(tools, path, info)


def response(frequency, key, center, q):
    relative = frequency / center
    if key == "air":
        return relative ** 4 / (1 + relative ** 4)
    return 1 / (1 + q ** 2 * (relative - 1 / relative) ** 2)


def match_curve(source, reference):
    comparable = min(source["sampleRate"], reference["sampleRate"]) * 0.45
    src, ref = source["spectrumDb"], reference["spectrumDb"]
    src_floor, ref_floor = max(src) - 48, max(ref) - 48
    valid = [index for index, freq in enumerate(BANDS)
             if freq < comparable and src[index] >= src_floor and ref[index] >= ref_floor]
    middle = [index for index in valid if 500 <= BANDS[index] <= 1750] or valid
    gains = [0.0] * len(FILTERS)
    if len(valid) >= 4 and middle:
        anchor = sum(ref[index] - src[index] for index in middle) / len(middle)
        targets = [limit(ref[index] - src[index] - anchor, -12, 12) for index in valid]
        rows = [[response(BANDS[index], key, freq, q) for key, freq, q, _ in FILTERS] for index in valid]
        # Bounded ridge fit with four coefficients. No boost where the source has no band.
        for _ in range(20):
            for column, (_, frequency, _, cap) in enumerate(FILTERS):
                if frequency >= comparable:
                    continue
                slope = 0.0
                weight = 0.7
                for row, target in zip(rows, targets):
                    residual = target - sum(value * gain for i, (value, gain) in enumerate(zip(row, gains)) if i != column)
                    slope += row[column] * residual
                    weight += row[column] ** 2
                gains[column] = limit(slope / weight, -cap, cap)
    positive = sum(max(gain, 0) for gain in gains)
    if positive > 4.98:
        gains = [gain * 4.98 / positive if gain > 0 else gain for gain in gains]
    curve = {key: round(gain, 2) for (key, _, _, _), gain in zip(FILTERS, gains)}
    excess = max(0, source["speechSpread"] - reference["speechSpread"] - 1)
    curve.update(threshold=round(limit(source["speechRms70"] - 1.5, -32, -10), 1),
                 ratio=round(1 + min(2, excess / 6), 2))
    return curve


def tone_filters(curve, args):
    # A 2-pole 70 Hz high-pass matches the track recipe. Level mode skips it.
    filters = ["highpass=f=70:p=2"]
    for key, frequency, q, _ in FILTERS:
        strength = args.depth if key in ("body", "mud") else args.presence
        gain = curve[key] * strength / 100
        if abs(gain) < 0.015:
            continue
        kind = "highshelf" if key == "air" else "equalizer"
        filters.append(f"{kind}=f={frequency}:t=q:w={q}:g={gain:.3f}")
    ratio = 1 + (curve["ratio"] - 1) * args.control / 100
    if args.mode == "voice" and ratio > 1.02:
        amplitude = 10 ** (curve["threshold"] / 20)
        filters.append(f"acompressor=threshold={amplitude:.7f}:ratio={ratio:.4f}:attack=12:release=120:knee=2.5:link=maximum:detection=rms")
    return filters


def prepare_output(path, suffix):
    if not path.parent.is_dir():
        raise ValueError("The output folder does not exist.")
    if os.path.lexists(path):
        raise ValueError("An output with that name exists. Choose a new name.")
    handle, name = tempfile.mkstemp(prefix=".voice-macro-", suffix=suffix, dir=path.parent)
    os.close(handle)
    return Path(name)


def publish(temp, path):
    # Reserve the name exclusively. Works on NTFS and removable exFAT drives.
    handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(handle)
    try:
        os.replace(temp, path)
    except OSError:
        path.unlink()
        raise


def write_json(path, values):
    if path.suffix.lower() != ".json":
        raise ValueError("Use a .json output path.")
    temp = prepare_output(path, ".json")
    try:
        temp.write_text(json.dumps(values, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        publish(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def render(tools, path, info, output, filters, gain):
    run(ffmpeg_input(tools, path) + ["-y", "-af", ",".join([*filters, f"volume={gain:.3f}dB"]),
                                    "-map_metadata", "-1", "-map_chapters", "-1", "-c:a", "pcm_s24le",
                                    "-rf64", "auto", str(output)])
    checked = wav_info(tools, output)
    for key in ("frames", "channels", "rate"):
        if checked[key] != info[key]:
            raise ValueError("Render changed the WAV channel layout, rate or duration.")
    return measure(tools, output, checked)


def process_match(args, tools, info, reference, source, curve):
    if args.output.suffix.lower() != ".wav":
        raise ValueError("Use a new .wav output path.")
    temp = prepare_output(args.output, ".wav")
    try:
        filters = [] if args.mode == "level" else tone_filters(curve, args)
        processed = source if not filters else measure(tools, args.input, info, filters)
        if args.mode == "eq" or args.loudness == "keep":
            target = source["loudness"]
        elif args.loudness == "youtube":
            target = -16.0
        else:
            target = reference["loudness"]
        requested = target - processed["loudness"]
        gain = min(requested, MAX_GAIN, CEILING - 0.08 - processed["truePeak"])
        after = render(tools, args.input, info, temp, filters, gain)
        if after["truePeak"] > CEILING:
            gain -= after["truePeak"] - CEILING + 0.10
            after = render(tools, args.input, info, temp, filters, gain)
        if after["truePeak"] > CEILING:
            raise ValueError("Could not verify the true-peak ceiling. The output was not saved.")
        publish(temp, args.output)
    finally:
        temp.unlink(missing_ok=True)
    print(f"Input: {source['loudness']:.2f} LUFS / {source['truePeak']:.2f} dBTP")
    print(f"Output: {after['loudness']:.2f} LUFS / {after['truePeak']:.2f} dBTP")
    print(f"Requested: {target:.2f} LUFS. Applied gain: {gain:+.2f} dB.")
    if after["loudness"] < target - 0.5:
        print("The headroom or gain limit kept the output below the requested loudness.")


def percentage(value):
    amount = float(value)
    if not number(amount, 0, 100):
        raise argparse.ArgumentTypeError("Enter a value from 0 to 100.")
    return amount


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("profile", "plan", "match"):
        command = actions.add_parser(name)
        command.add_argument("input", type=Path, help="input speech WAV")
        command.add_argument("--output", required=True, type=Path, help="new output path")
        if name != "profile":
            command.add_argument("--reference", type=Path, help="reference WAV or profile JSON")
        if name == "match":
            command.add_argument("--mode", choices=("voice", "eq", "level"), default="voice")
            command.add_argument("--loudness", choices=("reference", "youtube", "keep"), default="reference")
            command.add_argument("--depth", type=percentage, default=75)
            command.add_argument("--presence", type=percentage, default=75)
            command.add_argument("--control", type=percentage, default=45)
    args = parser.parse_args(argv)
    args.input = args.input.resolve()
    # Keep the final component unresolved so a dangling symlink still counts as occupied.
    args.output = args.output.parent.resolve() / args.output.name
    if getattr(args, "reference", None) is not None:
        args.reference = args.reference.resolve()
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if os.path.lexists(args.output):
            raise ValueError("An output with that name exists. Choose a new name.")
        tools = media_tools()
        info = wav_info(tools, args.input)
        if args.action == "profile":
            values = profile(tools, args.input, info)
            write_json(args.output, values)
            print(f"Reference: {values['loudness']:.2f} LUFS / {values['truePeak']:.2f} dBTP")
            return 0
        tone = args.action == "plan" or args.mode != "level"
        need_reference = tone or args.loudness == "reference"
        if need_reference and args.reference is None:
            raise ValueError("Choose a reference WAV or reference profile JSON.")
        reference = read_reference(tools, args.reference, tone) if need_reference else None
        source = profile(tools, args.input, info) if tone else measure(tools, args.input, info)
        curve = match_curve(source, reference) if tone else None
        if args.action == "plan":
            write_json(args.output, {"type": PLAN_TYPE, "schema": 1, **curve})
            print("Track match calculated. Use the VoiceMacro knobs to scale the correction.")
        else:
            process_match(args, tools, info, reference, source, curve)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"VoiceMacro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
