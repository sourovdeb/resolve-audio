# Design and logic

Target: Resolve Studio 21, Windows.
Date: 25 November 2026.

## Decision

Your requirement preserves Fairlight's processors.
The prototype therefore controls their interface.
It contains no audio-processing engine.
It contains no pitch shifter.

No EQ/Dynamics setters were established.
That is this investigation's finding.
It isn't proof against future APIs.
Your installed SDK remains authoritative.
The included inspection script reads it.

The supplied link describes Workflow Integrations.
That creates panels and invokes scripting.
It doesn't supply Fairlight parameter access.
Its overview dates from August 2020.

| Interface | Relevant role |
|---|---|
| OpenFX | Image effects |
| Workflow Integrations | Panels and scripting calls |
| VST3 | Audio processors hosted by Resolve |
| This controller | Fairlight mouse/keyboard operations |

A VST3 would process audio itself.
It wouldn't reuse Fairlight's EQ engine.
This prototype retains your chosen processors.
It pays for that with setup.

## Control path

1. Knobs produce seven numbers.
2. Stored mappings locate numeric fields.
3. Process, title, size, DPI checked.
4. Current field values are copied.
5. Recovery values are saved first.
6. Numeric values are entered.
7. Each change is read back.
8. All results are checked again.

Native input uses Windows SendInput.
The controller accepts Resolve process windows.
Only the process name is checked.
It doesn't authenticate Blackmagic's executable signature.
Window titles anchor the mappings.
Each group requires one window.
Duplicate coordinates are rejected.
Cross-track group mappings are rejected.
These checks cannot identify field semantics.
The operator must map correct labels.

Copied numbers prove numeric focus.
They don't prove the field's identity.
Final readback detects many mapping collisions.
It doesn't assess audible results.

Focus loss stops further writes.
Partial updates aren't silently rolled back.
Restore uses the saved values.
Clipboard formats are restored afterward.
Clipboard providers may reject restoration.
Such failures are reported.

No project database is patched.
No timeline preset is applied automatically.
No Resolve API method is invented.
No audio leaves the machine.

## Mathematics

Let D, P, C span 0–1.
Displayed knobs span 0–100.
Values round to 0.1.

| Field | Mapping | Range |
|---|---|---|
| Band 2 gain | 3.5 × D | 0…+3.5 dB |
| Band 3 gain | −2.5 × D | 0…−2.5 dB |
| Band 4 gain | 2.5 × P | 0…+2.5 dB |
| Band 5 gain | P² | 0…+1.0 dB |
| Compressor threshold | −18 − 8 × C | −18…−26 dBFS |
| Compressor ratio | 1 + 2.5 × C | 1:1…3.5:1 |
| Makeup gain | 3 × C | 0…+3 dB |

These are authored starting ranges.
They aren't microphone-transfer measurements.
They aren't trained on your voice.
Threshold depends on recording level.
Makeup gain isn't loudness normalization.
More compression can reveal room noise.
High-frequency boosts can emphasize sibilance.

Depth changes spectral balance.
It doesn't change the fundamental frequency.
The two EQ changes interact.
Actual summed response isn't their arithmetic sum.
Fairlight computes the resulting filters.

## Fixed setup

| Processor | Setup |
|---|---|
| Track EQ | Enabled; Earth type; Bands 1–5 enabled |
| Band 1 | High-pass; 70 Hz; 12 dB/octave |
| Band 2 | Bell; 140 Hz; Q 0.8 |
| Band 3 | Bell; 320 Hz; Q 1.0 |
| Band 4 | Bell; 3,200 Hz; Q 1.0 |
| Band 5 | High shelf; 10,000 Hz; Q 0.7 |
| Band 6 | Disabled |
| EQ output | 0 dB |
| Compressor | Enabled |
| Attack / Hold / Release | 10 ms / 0 ms / 120 ms |
| Knee | 20 on Resolve's scale |
| Mix | 0; verify processed signal |
| Sidechain | Disabled |
| Expander / Gate / Limiter | Disabled for this prototype |

Knee 20 isn't 20 dB.
Check Mix against your installed manual.
This baseline isn't measurement-derived.
Adjust the high-pass if needed.
Seventy hertz can thin some voices.

Prepare speech peaks around −12 dBFS.
Listen while monitoring gain reduction.
Aim initially around 2–4 dB reduction.
Reduce Control if consonants lose impact.
Check output peaks after every change.
Leave headroom at the output.

The prototype promises no peak ceiling.
It includes no true-peak meter.
Delivery loudness needs Resolve's measurement tools.

Optional cleanup remains outside the macros.
Use de-essing when sibilance requires it.
Use noise reduction when noise requires it.
Don't enable every effect by default.

## Preset layers

| Layer | Contains | Stored by |
|---|---|---|
| Macro JSON | Name; three knob positions | Voice Macro |
| Layout JSON | Window titles; field coordinates | Voice Macro |
| Recovery JSON | Before-change values; mapping identity | Voice Macro |
| Track preset | Track processor/settings state | Resolve |

Macro presets don't contain the baseline.
Fairlight presets can preserve that baseline.
Keep a track template after setup.

## Evidence

Primary documentation supports processor availability.
Native input behavior uses Microsoft's documentation.
Actual host behavior needs local testing.

- [Blackmagic: Fairlight](https://www.blackmagicdesign.com/products/davinciresolve/fairlight)
- [Blackmagic: developer portal](https://www.blackmagicdesign.com/developer/)
- [Blackmagic: release summaries](https://www.blackmagicdesign.com/support/partial/llm-release-notes-summary)
- [Blackmagic: Fairlight training, Resolve 18](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-18-Fairlight-Audio-Post.pdf)
- [OpenFX: documentation](https://openfx.readthedocs.io/en/main/)
- [Steinberg: VST3 developer portal](https://steinbergmedia.github.io/vst3_dev_portal/pages/index.html)
- [Microsoft: SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [Microsoft: GetWindowThreadProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid)
- [Supplied Workflow Integrations mirror](https://resolvedevdoc.readthedocs.io/en/latest/readme_workflow.html)

The last source is community-hosted.
It reproduces Blackmagic's documentation.
It isn't authoritative for every 21.x build.

Preset workflow reference: printed pages 475–476.
Those correspond to PDF pages 499–500.
Menu wording may differ in 21.
