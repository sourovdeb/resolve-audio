# Review of supplied versions

I inspected both ZIP archives.
I read the separate Python file.
I read the supplied plan.
I inspected the rectangle sketch.

## Findings

| Input | Finding | Consequence |
|---|---|---|
| xai ZIP | Knobs calculate a recipe | EQ/Dynamics aren't updated by knobs |
| xai ZIP | Preset application targets the timeline | Not equivalent to track knob control |
| xai ZIP | Control zero retains 1.5:1 compression | Zero doesn't mean stage bypass |
| xai ZIP | Control zero retains +2 dB makeup | Loudness affects comparisons |
| GLM ZIP | EQ/Dynamics values are printed | The desired control link remains missing |
| GLM ZIP | Voice Isolation targets track 1 | Selection wording doesn't match targeting |
| GLM ZIP | A None result becomes success | Success isn't demonstrated |
| GLM ZIP | Recipe duplicates shelf across bands 5/6 | Recipe and preview EQ can diverge |
| GLM ZIP | Uses assumed −50 dBFS noise floor | Expansion isn't recording-adaptive |
| GLM ZIP | Existing suite passes 22 checks | None validates Resolve UI operation |
| Separate voice_macro.py | Limiter startup test exceeds ceiling | Stated ceiling isn't guaranteed |
| Both DSP copies | Empty/short/8 kHz cases fail | Input domain needs validation |
| Supplied plan | Quality probabilities lack listening evidence | Percentages aren't reliability measurements |

These findings concern the supplied files.
They aren't claims about model families.

## Reproduced checks

Existing GLM suite: **22/22 passed**.
This confirms those specific assertions.
It doesn't validate the host integration.

| Input | Separate Python | GLM Python |
|---|---|---|
| Empty; 48 kHz | ValueError | ValueError |
| 20 samples; 48 kHz | IndexError | IndexError |
| 4,000 samples; 8 kHz | ValueError | ValueError |
| Limiter-only startup impulse | +19.917 dBFS | −1.000 dBFS |

Startup impulse amplitude was 10.0.
It was sample zero of 2,000.
The requested ceiling was −1 dBFS.
That isolates limiter startup behavior.
It isn't a speech-quality test.

The GLM limiter fixes that case.
The standalone file doesn't.
They should not be treated identically.

## What changed

The new executable controls numeric fields.
It doesn't claim an undocumented API.
Its baseline uses four shaping bands.
Band 6 stays disabled.
Macro gains vanish at zero.
High-pass filtering remains enabled.
Compression ratio becomes 1:1 at zero.
Makeup becomes 0 dB at zero.

Input access requires readback.
Backups precede value changes.
Status never equates requests with success.
Final readback checks the whole batch.
No audio-quality claim comes from tests.

## Remaining uncertainty

Resolve isn't installed in this environment.
The Windows desktop wasn't available either.
Clipboard behavior remains host-dependent.
Field focus remains host-dependent.
Your source recording wasn't provided.
Therefore, no listening improvement is established.

Compilation and logic tests are evidence.
They aren't Windows acceptance testing.
They aren't microphone equivalence testing.
