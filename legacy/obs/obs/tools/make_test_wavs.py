#!/usr/bin/env python3
"""Make synthetic speech-like test WAVs that imitate the device MOV in the
user's render table: -21.05 LUFS / -0.77 dBTP, 4.4 LU wider spread than the
reference, thin presence vs the H1n profile. No network, pure numpy.

Usage: make_test_wavs.py OUTDIR
Creates OUTDIR/device_take.wav (48k stereo 16-bit, ~90 s of speech-like audio
with pauses) shaped so its 15-band profile differs from the reference.
"""
import sys
from pathlib import Path

import numpy as np

RATE = 48000
BANDS = np.array([100, 140, 200, 280, 400, 560, 800, 1120, 1600, 2240, 3200, 4480, 6400, 9000, 10900], float)
REF_DB = np.array([-4.792, -10.898, -9.616, -7.045, -10.799, -13.431, -20.293, -21.599,
                   -17.472, -17.852, -19.992, -16.201, -14.436, -16.115, -21.818])


def band_noise(n, bands, weights_db, rng):
    """Sum of band noises built from a single noise spectrum with per-band
    gains, so the shape is continuous (no holes) and reproducible."""
    weights = 10 ** (weights_db / 20)
    spec = (rng.standard_normal(n // 2 + 1) + 1j * rng.standard_normal(n // 2 + 1)) / np.sqrt(2)
    # Per-bin gain: piecewise-linear in log-frequency across band centres.
    log_f = np.log(np.maximum(np.fft.rfftfreq(n, 1 / RATE), 1.0))
    log_bands = np.log(bands)
    band_gain = np.interp(log_f, log_bands, weights, left=weights[0], right=weights[-1])
    return np.fft.irfft(spec * band_gain, n)


def envelope(n, rng):
    """Speech-like syllable envelope: word bursts (2-6 Hz) inside sentence
    bursts with gaps, plus real level variation between sentences (12 dB range,
    matching a casual device recording)."""
    t = np.arange(n) / RATE
    syll = 0.55 + 0.45 * np.abs(np.sin(2 * np.pi * 3.3 * t + rng.uniform(0, 6)))
    sent_gate = np.zeros(n)
    pos = int(RATE * 0.3)
    while pos < n:
        length = int(RATE * rng.uniform(2.5, 6.0))
        fade = min(RATE // 20, length // 6)
        ramp = np.ones(length)
        ramp[:fade] = np.linspace(0, 1, fade)
        ramp[-fade:] = np.linspace(1, 0, fade)
        end = min(pos + length, n)
        # Sentence emphasis: some sentences 8 dB hotter, some 4 dB softer.
        sent_gate[pos:end] = ramp[: end - pos] * 10 ** (rng.uniform(-4, 8) / 20)
        pos = end + int(RATE * rng.uniform(0.4, 1.8))
    return syll * sent_gate


def fundamental_track(n, rng):
    """Slowly wandering f0 around 130 Hz (male-ish reading voice)."""
    t = np.arange(n) / RATE
    f0 = 125 + 18 * np.sin(2 * np.pi * 0.11 * t) + 6 * np.sin(2 * np.pi * 0.7 * t + 1.2)
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    # Glottal-ish pulse train: sum of harmonics with 1/k spectral slope.
    sig = np.zeros(n)
    for k in range(1, 40):
        if k * 135 >= RATE / 2:
            break
        sig += np.sin(k * phase + rng.uniform(0, 6)) / (k ** 0.9)
    return sig / 8.0


def write_wav(path, left, right):
    peak = max(np.abs(left).max(), np.abs(right).max())
    gain = 0.35 / peak  # conservative analogue-style headroom before shaping
    left, right = left * gain, right * gain
    data = np.empty(left.size * 2, np.int16)
    data[0::2] = np.clip(left * 32767, -32768, 32767).astype(np.int16)
    data[1::2] = np.clip(right * 32767, -32768, 32767).astype(np.int16)
    import struct

    with open(path, "wb") as fh:
        fh.write(b"RIFF")
        fh.write(struct.pack("<I", 36 + data.nbytes))
        fh.write(b"WAVEfmt ")
        fh.write(struct.pack("<IHHIIHH", 16, 1, 2, RATE, RATE * 4, 4, 16))
        fh.write(b"data")
        fh.write(struct.pack("<I", data.nbytes))
        fh.write(data.tobytes())


def main():
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    outdir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261125)
    n = RATE * 90

    # Device take: thin presence (cut 2.2-6.4 kHz), slightly heavy mud,
    # wide dynamics like a handheld recorder (spread ~16 vs 11.96 reference).
    dev_weights = REF_DB + np.array([+0.5, +0.5, +0.5, +1.5, +2.5, +1.5, 0, 0, 0, -4, -6, -6, -6, -7, -8])
    excitation = band_noise(n, BANDS, dev_weights, rng)
    source = fundamental_track(n, rng) + 0.8 * excitation
    env = envelope(n, rng)
    left = source * env
    right = left * 0.96 + 0.05 * band_noise(n, BANDS, REF_DB, rng) * env
    write_wav(outdir / "device_take.wav", left, right)

    # Quiet headset take: closer, tighter, duller, lower level.
    head_weights = REF_DB + np.array([+1, +1, +1, +1, 0, 0, 0, 0, 0, -2, -3, -4, -5, -6, -7])
    excitation = band_noise(n, BANDS, head_weights, rng)
    source = fundamental_track(n, rng) + 0.8 * excitation
    env = envelope(n, rng)
    left = source * env
    right = left * 0.97 + 0.03 * band_noise(n, BANDS, REF_DB, rng) * env
    write_wav(outdir / "headset_quiet.wav", left, right)

    # Hot wide-dynamics take: peaks near -0.8 dBTP (like the device MOV),
    # spread ~16 dB (wider than the reference 11.96) -> exercises compressor
    # and the peak-crowding case where the old pipeline's gain clamp failed.
    excitation = band_noise(n, BANDS, dev_weights, rng)
    source = fundamental_track(n, rng) + 0.8 * excitation
    env = envelope(n, rng)
    # Exaggerate sentence-level swing and add occasional emphasis spikes.
    env = env * (1 + 0.35 * (env > np.quantile(env, 0.98)))
    left = source * env
    right = left * 0.96 + 0.05 * band_noise(n, BANDS, REF_DB, rng) * env
    left, right = normalize_pair(left, right, peak_dbfs=-0.8)
    write_wav(outdir / "hot_wide.wav", left, right)


def normalize_pair(left, right, peak_dbfs):
    peak = max(np.abs(left).max(), np.abs(right).max())
    gain = (10 ** (peak_dbfs / 20)) / peak
    return left * gain, right * gain

    for name in ("device_take.wav", "headset_quiet.wav"):
        p = outdir / name
        print(f"{name}: {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
