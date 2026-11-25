# VoiceMacro 0.4

For DaVinci Resolve Studio 21 on Windows. Open [START-HERE.html](START-HERE.html) for installation, mapping, and the steps for each Resolve menu.

## Install

1. Extract the whole ZIP.
2. Close Resolve and VoiceMacro.
3. Run `install\Install-VoiceMacro.cmd`.
4. Restart Resolve Studio.
5. Open **Workspace → Workflow Integrations → VoiceMacro**.

The installer also adds **Workspace → Scripts → VoiceMacro** for the current user. The ZIP includes `VoiceMacro.exe` for running without installation. The launcher uses Resolve's Workflow Integration format. The app uses .NET Framework 4.8. Windows and Resolve testing remains pending.

## Controls

| Control | Use |
|---|---|
| Depth, Presence, Control | Shape voice or scale a WAV-derived match. |
| Track profiles | Copy and paste mapped voice, EQ, compressor, or fader values. |
| Match WAV | Match voice, EQ, or level. Create a new WAV or load a curve for the knobs. |
| Resolve tools | Find the built-in capture, paste, and save commands. |
| Save | Store knobs and the loaded match curve as JSON. |

For direct Fairlight processing, configure the band frequencies and compressor switches in **Recipe**. Map the numeric fields in **Setup** and verify each group. **Apply** writes mapped values and reads them back. The fader mapping is optional and operates through **Track profiles**. For full module copying, use Resolve's mixer graph context menus. For saving a Resolve preset, use **Fairlight → Presets Library**. For a mixer snapshot, use **Fairlight → Automation → Mix List → Save Mix**.

## Match WAVs with Python

Requirements for WAV matching: Python 3.9+ and FFmpeg with `ffprobe` on PATH. The `install\Install-Matcher-Tools.cmd` helper uses Windows Package Manager. Restart Resolve after installing dependencies. The matcher runs without models or network access.

```powershell
py -3 matcher\match_voice.py profile "reference.wav" --output "Reference-Profile.json"
py -3 matcher\match_voice.py match "target.wav" --reference "Reference-Profile.json" --output "matched.wav" --loudness youtube
py -3 matcher\match_voice.py plan "target.wav" --reference "Reference-Profile.json" --output "Track-Plan.json"
```

- The reference argument accepts a speech WAV or a profile from `profile`.
- Select `--mode voice`, `--mode eq`, or `--mode level`. `voice` is the default.
- `--loudness reference` is the default. `youtube` targets −16 LUFS with a −2 dBTP ceiling. `keep` aims for the target's original measured loudness. `eq` always uses the original measured loudness as its target.
- `--depth`, `--presence`, and `--control` range from 0 to 100. WAV output retains sample rate, channels, and frame count. It uses 24-bit PCM and a new filename.
- Use **Track profiles → Load WAV match plan** to import `Track-Plan.json`, or select **Match WAV → Use with knobs**. Choose an isolated target speech recording. The plan uses one EQ curve for the track. Check Resolve's final meter separately.

## Build and verify

```powershell
dotnet build VoiceMacro.csproj -c Release
dotnet run --project tests/Tests.csproj -c Release
python -m unittest discover -s tests -p "test_matcher.py"
```

See [validation](docs/VALIDATION.md) for tested cases and the Windows checklist. Source is under the MIT license in [LICENSE.txt](LICENSE.txt).
