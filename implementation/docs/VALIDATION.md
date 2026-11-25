# Validation

## Completed

| Check | Result |
|---|---|
| Windows-target compilation | Pass; zero warnings/errors |
| Logic/failure test groups | 26 passed |
| Randomized knob combinations | 10,000 checked |
| Preset save/load/replacement | Passed |
| Invalid preset rejection | Passed |
| Numeric clipboard parsing | Passed |
| Backup failure behavior | No parameter writes |
| Readback mismatch behavior | Stops subsequent writes |
| Field aliasing | Detected by final readback |
| Recovery values | Preserved before writes |
| Duplicate mapped coordinates | Rejected |
| Cross-track EQ mapping | Rejected |
| Windows UI execution | Not tested here |
| Resolve Studio 21 execution | Not tested here |
| Your voice quality | Not tested here |

The bridge failure tests use fakes.
They test the transaction logic.
They don't exercise Windows SendInput.
The actual Windows bridge was compiled.

## First Resolve test

1. Duplicate a timeline for testing.
2. Keep one speech track selected.
3. Configure the baseline through Recipe.
4. Open EQ and Dynamics windows.
5. Map seven numeric fields.
6. Verify their identities and values.
7. Load the Voice preset.
8. Click Apply.
9. Inspect all seven changed numbers.
10. Play the speech passage.
11. Click Restore; inspect the numbers.
12. Verify mapping after restarting.

Move a floating window afterward.
Its same-DPI mapping should follow.
Change display scaling; expect rejection.
Cover a field; expect rejection.
Press Escape during application; inspect values.
Some earlier writes may remain.

If copying fields fails, stop testing.
The app will block writes.
Use the displayed recipe instead.
That is manual operation.

## Listening without suggestion

Use the same 20-second speech passage.
Include pauses, consonants, and sibilants.
Render the baseline and processed versions.
Keep timing and channel layouts identical.
Measure both with Resolve's loudness meter.
Match integrated loudness within 0.5 LU.
Don't judge improvement from volume increases.

Ask someone to hide filenames.
Listen without knowing the version.
Compare intelligibility and listening fatigue.
Check sibilance, pumping, noise, and clipping.
Repeat across several passages.
Keep processing only when you prefer it.

| Question | Pass condition |
|---|---|
| Words remain understandable? | No consonants disappear |
| Bass supports the voice? | No excess rumble |
| Pauses sound acceptable? | No distracting noise swelling |
| Sibilance stays controlled? | No painful emphasis |
| Levels stay consistent? | No audible pumping |
| Delivery meter passes? | Your platform target is met |
| Blind preference improves? | Repeat preference across passages |

There is no universal microphone preset.
A recording sample enables further tuning.
