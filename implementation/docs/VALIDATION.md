# VoiceMacro 0.4 validation

| Check | Result |
|---|---|
| Windows-target build | Pass, zero warnings or errors |
| C# logic and failure handling | 29 groups passed |
| Python and FFmpeg matcher | Six tests passed |
| Installer manifest and package entry | IDs and entry file agree |
| Electron launcher JavaScript | Syntax checked |
| Installer and Workflow menu in Resolve | Windows host test pending |
| Numeric field operations in Fairlight | Windows host test pending |

The matcher tests cover reference and track JSON, same-tone identity, spectral and level correction, true-peak headroom, stereo phase, 8 kHz bandwidth, silence, and existing output names. The C# tests exercise settings and validation with a simulated field bridge.

## Windows acceptance test

1. Close Resolve and install from the extracted folder.
2. Start Resolve Studio 21 and open VoiceMacro from **Workspace → Workflow Integrations**.
3. Open a copy of the timeline and select its speech track.
4. Prepare track EQ and Dynamics from **Recipe**. Map and verify both groups. Confirm the displayed readback values.
5. Apply the Voice preset. Verify the new values in Fairlight. Use **Restore** and check the previous values.
6. Copy EQ and paste it onto a verified destination with the same baseline. Confirm Dynamics stays unchanged.
7. Map the mixer fader. Copy and paste it separately. Confirm the destination fader before playback.
8. Make a WAV reference match. Import the result and compare at the same loudness.
9. Save a native track preset and a Mix List snapshot. Reopen each panel to confirm the entry.

Leave enough headroom for the complete mix. The measured WAV ceiling applies to the generated file. Resolve's track processing and final encoding have their own signal paths.
