# Voice Macro 0.3

For Resolve Studio 21. Windows 10/11.

**This is a controller prototype.**
It uses Fairlight's EQ and Dynamics.
It sends mouse and keyboard input.
Audio stays inside Resolve.

**Setup comes before knob control.**
Windows/Resolve operation remains untested here.
Audio improvement remains unmeasured.

## Start

1. Extract the ZIP.
2. Open **START-HERE.html**.
3. Run **VoiceMacro.exe**.
4. Complete **Recipe** setup.
5. Map seven fields through **Setup**.
6. Choose **Verify mappings**.
7. Adjust knobs; click **Apply**.

Windows supplies .NET Framework 4.8.
Python, Electron, and accounts aren't required.
The application makes no network requests.
The executable has no signing certificate.

## Knobs

| Knob | Changes |
|---|---|
| Depth | Body boost; mud reduction |
| Presence | Presence boost; treble shelf |
| Control | Threshold; compression ratio; makeup gain |

After verification, enable **Apply on release**.
Drag vertically; release to apply.
Arrow keys adjust each knob.
Shift reduces mouse sensitivity.
Keep the EQ/Dynamics windows open.
Keep hands off during application.
Escape stops the operation.

Changes take several seconds.
This isn't sample-by-sample knob automation.
The processing itself remains in Fairlight.
Closing Voice Macro preserves applied settings.

## Save

**Save** stores knob positions as JSON.
**Load** restores those positions.
Click **Apply** after loading.
JSON isn't a Fairlight preset.

For saving inside Resolve:

1. Open **Fairlight → Presets Library**.
2. Select your voice track.
3. Select **Global Track Presets**.
4. Click **Save New**.
5. Name and save the preset.

Global presets include other track settings.
Alternatively, save EQ/Dynamics presets separately.
Menu wording can vary across builds.

## Limits

- Setup includes frequencies and switches.
- Mapping covers seven numeric controls.
- Mapping doesn't identify audio content.
- Check the track window titles.
- Readback requires copying field text.
- Unsupported copying blocks automatic application.
- Layout or DPI changes require remapping.
- Track changes can require remapping.
- Verify mappings after each launch.
- Zero knobs retain high-pass filtering.
- This doesn't lower vocal pitch.
- It doesn't repair clipped recordings.
- It doesn't replace microphone technique.
- Loudness targets aren't applied automatically.

If control fails, use **Recipe**.
Enter its numbers through Fairlight.
This fallback requires manual entry.

## Restore

**Restore** reverses the last applied batch.
It uses stored parameter values.
It doesn't restore the whole track.
With release mode, batches cover groups.
Restoring doesn't reposition the knobs.
Knobs continue showing proposed settings.

Interrupted batches can leave changes.
Inspect the values before restoring.
The application retains recovery snapshots.

## Files

| File | Purpose |
|---|---|
| VoiceMacro.exe | Windows application |
| START-HERE.html | Setup walkthrough |
| presets/ | Three starting presets |
| docs/ENGINEERING.md | Design and formulas |
| docs/REVIEW.md | Attachment review |
| docs/VALIDATION.md | Tests and listening protocol |
| docs/TEST-RESULTS.txt | Executed logic tests |
| docs/BUILD-RESULTS.txt | Windows-target compilation |
| src/ | Application source |
| tests/ | Logic and failure tests |
| tools/Inspect-ResolveDocs.ps1 | Read installed SDK documentation |

Settings use `%LOCALAPPDATA%\VoiceMacro`.
Presets remain portable JSON files.
Deleting the application removes no audio.

## Rebuild

Use a .NET 8 SDK.
The application targets .NET Framework 4.8.

```powershell
dotnet build VoiceMacro.csproj -c Release
dotnet run --project tests/Tests.csproj -c Release
```

Only rebuilding downloads reference assemblies.
Running the application requires no downloads.

License: MIT. See LICENSE.txt.
Blackmagic hasn't endorsed this prototype.
