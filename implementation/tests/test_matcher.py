import array
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave


MATCHER_DIR = Path(__file__).resolve().parents[1] / "matcher"
sys.path.insert(0, str(MATCHER_DIR))
import match_voice as matcher


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="VoiceMacro tests ")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.tools = matcher.media_tools()

    def write_wav(self, name, rate=48000, stereo=False, silence=False, impulse=False):
        path = self.directory / name
        samples = array.array("h")
        tones = ((140, .035), (320, .025), (536, .020), (820, .026), (1120, .026),
                 (2240, .018), (3200, .025), (4480, .013), (9100, .015))
        tones = [(f, gain) for f, gain in tones if f < rate * 0.45]
        for frame in range(3 * rate):
            time = frame / rate
            signal = 0 if silence else sum(g * math.sin(math.tau * f * time) for f, g in tones)
            signal *= 0.68 + 0.25 * math.sin(math.tau * 1.4 * time)
            value = int(32767 * signal)
            if impulse and frame == rate:
                value = 32760
            samples.append(value)
            if stereo:
                samples.append(-value)
        if sys.byteorder != "little":
            samples.byteswap()
        with wave.open(str(path), "wb") as output:
            output.setnchannels(2 if stereo else 1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(samples.tobytes())
        return path

    def cli(self, *args):
        return subprocess.run([sys.executable, str(MATCHER_DIR / "match_voice.py"), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    def measure(self, path):
        return matcher.measure(self.tools, path, matcher.wav_info(self.tools, path))

    def profile(self, path):
        return matcher.profile(self.tools, path, matcher.wav_info(self.tools, path))

    def test_identical_tone_needs_no_matching_boost(self):
        source = self.profile(self.write_wav("Original.wav"))
        curve = matcher.match_curve(source, source)
        self.assertEqual([curve[k] for k, _, _, _ in matcher.FILTERS], [0, 0, 0, 0])
        self.assertEqual(curve["ratio"], 1)

    def test_profile_roundtrip_guide_and_render(self):
        ref = self.write_wav("Reference.wav")
        profile = self.directory / "Reference profile.json"
        target = self.directory / "Target.wav"
        plan = self.directory / "Plan.json"
        matched = self.directory / "Matched.wav"
        result = self.cli("profile", ref, "--output", profile)
        self.assertEqual(result.returncode, 0, result.stderr)
        matcher.run(matcher.ffmpeg_input(self.tools, ref) + ["-af",
                    "equalizer=f=3200:t=q:w=1:g=-6,volume=-6dB", "-c:a", "pcm_s24le", str(target)])
        result = self.cli("plan", target, "--reference", profile, "--output", plan)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = matcher.json.loads(plan.read_text())
        self.assertEqual(values["type"], matcher.PLAN_TYPE)
        self.assertGreater(values["presence"], 1)
        result = self.cli("match", target, "--reference", profile, "--output", matched)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(matcher.wav_info(self.tools, matched), matcher.wav_info(self.tools, target))
        reference = self.profile(ref)
        before = self.profile(target)
        after = self.profile(matched)
        presence_band = matcher.BANDS.index(3200)
        self.assertLess(abs(after["spectrumDb"][presence_band] - reference["spectrumDb"][presence_band]),
                        abs(before["spectrumDb"][presence_band] - reference["spectrumDb"][presence_band]))
        self.assertLess(abs(after["loudness"] - reference["loudness"]), 0.5)

    def test_peak_limit_takes_precedence(self):
        source = self.write_wav("Transient.wav", impulse=True)
        output = self.directory / "Level.wav"
        result = self.cli("match", source, "--mode", "level", "--loudness", "youtube", "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("headroom", result.stdout)
        self.assertLessEqual(self.measure(output)["truePeak"], matcher.CEILING)

    def test_low_rate_anti_phase_stereo(self):
        ref = self.profile(self.write_wav("Reference.wav"))
        input_wav = self.write_wav("Stereo.wav", rate=8000, stereo=True)
        profile = self.profile(input_wav)
        curve = matcher.match_curve(profile, ref)
        self.assertEqual(curve["air"], 0)
        self.assertGreater(max(profile["spectrumDb"]), -20)

    def test_silence_has_no_output(self):
        source = self.write_wav("Silence.wav", silence=True)
        output = self.directory / "Silent.json"
        result = self.cli("profile", source, "--output", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_existing_output_is_preserved(self):
        source = self.write_wav("Keep.wav")
        original = source.read_bytes()
        result = self.cli("match", source, "--mode", "level", "--loudness", "youtube", "--output", source)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
