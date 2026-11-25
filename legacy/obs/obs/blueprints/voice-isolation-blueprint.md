# OBS Voice Isolation

**App 2 of 2. Version 0.3 — built. Script shipped; plugin path defined.**
**Companion:** `voice-match-blueprint.json`. On the microphone, this filter sits **above** Voice Match.

The notes in `opinions/` are not this spec. Where they disagree, this file wins.

## What the toggle does

One control. The filter's eye icon, and one hotkey that flips it.

On: speech stays, steady noise is turned down (fan, hum, hiss, a lot of keyboard clatter).
Off: the microphone is untouched.

That is the whole product for the first version.

## What those words do not mean

"Keep the voice and remove the rest" hides three jobs. Only the first one is this toggle.

| Job | What it removes | What it leaves | In v1 |
|---|---|---|---|
| Noise removal | Fan, hum, hiss, a lot of room hiss | Other people, television dialogue, music | Yes. This is the toggle. |
| Speech cleanup | A moderate amount of music as well | Other people talking | No. Only if the tests below fail. |
| My voice only | Other people when you are not talking | Nobody, including you, when two people talk at once | No. A different project, after this one works. |

RNNoise, which OBS already ships, is a noise remover. It is not a "delete every voice except mine" switch. Building a second copy of it inside a new plugin does not make the first version better.

## What is built (v0.3)

`obs/script/isolate_voice.lua` — Lua, no dependencies, no Python setup:

- Creates (if missing) a `noise_suppress_filter` named **Voice Isolation (RNNoise)** on the chosen source, with `method = "rnnoise"`. Method and setting keys verified against the obs-studio source (`plugins/obs-filters/noise-suppress-filter.c`: `S_METHOD "method"`, `S_METHOD_RNN "rnnoise"`, `S_SUPPRESS_LEVEL "suppress_level"`).
- A **Toggle voice isolation** hotkey (`obs_hotkey_register_frontend`), saved and restored with the script.
- A checkbox for the initial state; the eye icon stays the real-time switch.
- Warns when another noise-suppression filter is already on the source (double processing).
- Fixed strength, hidden. RNNoise has one strength; `suppress_level` only applies to the speex fallback. No slider was asked for and none is given.

Why a script first, why Lua: OBS scripts have lifecycle, properties, tick and hotkey hooks and **no audio callback** (verified on docs.obsproject.com/scripting, OBS 33.0.3). A script cannot process samples, so it drives OBS's own filter. Lua ships inside OBS, so there is no interpreter setup step — the most common first-day failure of the App 1 script does not exist here.

## Chain order with App 1

1. Voice Isolation (this app)
2. Voice Match (App 1)
3. Nothing else that changes gain, compression or limiting on that source.

If the room is noisy, running Voice Match without isolation makes its learned tone curve less trustworthy; App 1 halves its correction automatically when it detects a poor speech-to-noise ratio.

## The plugin path (B2, second build)

Kept from the earlier plan, unchanged in intent, now with a concrete base:

- Template: `obs-plugin-template` (GPL-2.0), same build pipeline App 1's plugin already uses (`obs/plugin/` cmake tree is shared).
- Model candidate: DeepFilterNet-class speech enhancement (full-band 48 kHz, permissive licence, real-time on CPU) or embedded RNNoise. **Verify licence and version before committing code.**
- Worker-thread inference, lock-free rings on the audio thread, pass-through if the worker falls behind.
- Latency budget 20-40 ms; if that is too much for self-monitoring, keep B1.
- Decide from data, not vibes: record scenarios 1-8 below with B1 for a week first.

## Validation framework

Evidence rule: no claim of "it works" without a saved report. Record each scenario once with the toggle off, once on, same raw input.

| # | Scenario |
|---|---|
| 1 | Silence, 30 s (only the room) |
| 2 | Speech in a quiet room |
| 3 | Speech with a fan or air conditioner |
| 4 | Speech while typing |
| 5 | Speech with music at low volume |
| 6 | Speech with a TV or a second person talking |
| 7 | Whispering and shouting samples |
| 8 | Speech while a game and the video encoder are running |

| Metric | How | Pass |
|---|---|---|
| Noise reduction | Scenario 1 level, on vs off | at least 20 dB lower |
| Speech preserved | 15-band profile (App 1's analyser) of scenario 2, on vs off | each band within 1.5 dB |
| Word integrity | Listening, 10 sentences, clipped starts/ends | at most 1 in 10 |
| Keyboard | Scenario 4 listening | keystrokes not audible at normal volume |
| Background voice | Scenario 6 | remains (Tier A promise) |
| Latency | Clap test | recorded, compared with tolerance |
| CPU | Task Manager with a game running | chain under 5 percent, no encoder drops |
| Stability | 8-hour run | zero dropouts |

Use App 1's 15-band measurement for "Speech preserved" so both apps are judged with the same ruler.

## Failure modes

| ID | Trigger | Symptom | Branch |
|---|---|---|---|
| B1-1 | OBS build without RNNoise | Filter missing or errors | Script logs it; edit one line for `speex` |
| B1-2 | Over-suppression | Word endings clipped, underwater tone | Not adjustable in RNNoise; if it persists, that is the case for B2 |
| B1-3 | Another noise filter already present | Thin, double-processed voice | Script warns; remove the old one |
| B1-4 | Hotkey conflict | Toggle does nothing | Rebind in OBS Settings, Hotkeys |
| B2-1 | Model too heavy alongside OBS + game | Dropouts, CPU spikes | Smaller model or stay on B1 |
| B2-2 | Latency while self-monitoring | Echo, lip-sync drift | Sync offset; or disable monitoring through OBS |
| B2-3 | Artefacts on expressive speech | Warbling, swallowed syllables | Blend dry/wet; lower strength |
| B2-4 | Licence incompatibility | Cannot ship | Check before coding |

## Out of v1

One toggle. No strength control, no custom window, no cloud processing, no speaker identification.
