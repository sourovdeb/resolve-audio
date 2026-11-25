# VoiceMacro

The bundled [Zoom H1n reference](presets/Zoom-H1n-Voice-Reference.json) is selected on launch.

## Start on Windows

1. Extract the ZIP.
2. Run `VoiceMacro.exe`.
3. Choose the voice WAV. Matching starts.
4. Import the new `*-VoiceMacro.wav` into Resolve and listen.

Install Python 3 and FFmpeg if prompted. You can run `install\Install-Matcher-Tools.cmd` to install them with Windows Package Manager. The app is a standalone Windows program. The `install\Install-VoiceMacro.cmd` menu entry is optional.

The new WAV keeps the original file's duration, channels, and sample rate. The reference is a numerical JSON profile. The original reference WAV is not needed. The matcher measures the target, calculates a bounded EQ correction, uses gentle compression when indicated by the measurements, and checks the resulting true peak. The file's loudness may remain below the requested target when peaks limit gain.

## Run from a console

Double-click `Run-VoiceMacro.cmd` while Resolve is open. The script looks for linked WAV clips in the current timeline. It chooses the single clip automatically or asks you to choose among multiple clips. It writes a new WAV and imports it into the Media Pool.

Alternatively, give it a file path.

```powershell
py -3 voice_macro_console.py --input "C:\recordings\voice.wav"
```

The Python console script works without Resolve when you pass `--input`. It uses the same bundled reference and audio matching engine. `--loudness youtube` selects the −16 LUFS starting target. The output is limited to −2 dBTP. Default loudness follows the reference.

For an existing Resolve timeline clip, `--resolve-level` changes its clip gain only. It uses the `AnalyzeAudioLevels` and `SetProperties` calls listed in the supplied function notes. If your `resolve_audio_tools.py` is available, pass `--tools "C:\path\resolve_audio_tools.py"` to use its `set_gain_db` wrapper. The notes did not include the helper file itself. The script also works with Resolve's documented calls directly.

Resolve's scripting interface does not provide a per-band Fairlight EQ setter in the supplied function list. Matching tone therefore creates a WAV. The **Use with knobs** command proposes track EQ numbers for the existing mapped controller when you need that route.

## Files

- `VoiceMacro.exe` opens the matcher and starts matching after you choose a WAV.
- `Run-VoiceMacro.cmd` opens the Python console flow.
- `voice_macro_console.py` finds Resolve audio clips or accepts a WAV path.
- `presets/Zoom-H1n-Voice-Reference.json` contains the measured reference and its instructions.
- `matcher/match_voice.py` measures, matches, and writes audio.
- `docs/VALIDATION.md` records the remaining Windows host checks.

Run `py -3 voice_macro_console.py --help` for optional modes and paths.
