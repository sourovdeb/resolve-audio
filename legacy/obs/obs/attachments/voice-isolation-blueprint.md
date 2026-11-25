# OBS Voice Isolation (App 2 of 2): Blueprint

**Version:** 0.1-draft, 2026-11-25
**Status:** Blueprint only. No code written yet.
**Companion:** `voice-match-blueprint.json` (App 1). Chain order in OBS: **Isolation first, Voice Match second.** Voice Match measures the voice to learn its tone, and a clean signal gives it a cleaner measurement.

## 0. How to read this file

| Tag | Meaning |
|---|---|
| **Verified** | Checked this session against a fetched page. |
| **Recalled** | From my own knowledge of OBS and the tools named. Not re-checked. Confirm in the discovery task (section 3, step 1). |
| **Estimate** | My judgement of likelihood. Not measured. |

## 1. What "keep the voice, remove the rest" can mean

There are three different jobs hiding in that sentence. They differ a lot in difficulty, so the plan treats them as three tiers.

| Tier | What it does | Removes | Does not remove | Estimate that v1 works well |
|---|---|---|---|---|
| **A. Noise removal** | Keeps any speech, removes non-speech sound | Fans, hum, hiss, room noise, most keyboard and mouse clicks | Other people talking, TV dialogue, singing | about 85 percent for steady noise, about 60 percent for keyboard clicks |
| **B. Speech-only** | Tier A plus suppression of music and effects | Most background music at moderate level | Other voices | about 50 percent |
| **C. My voice only** | Keeps only an enrolled speaker | Other voices as well | Overlapping speech cannot be separated cleanly | about 35 percent for a good first version |

**Recommendation:** ship Tier A first, as one toggle. Treat Tier C as a later add-on, not part of the toggle's promise.

## 2. Architecture decision

- **Verified:** a Lua or Python OBS script has lifecycle and UI hooks (load, update, properties, tick) and can register hotkeys. It has no hook that receives audio samples. The documented hotkey function for scripts is `obs_hotkey_register_frontend`.
- **Consequence:** a script cannot do the isolation itself. It can only switch on OBS's own noise-suppression filter. A real custom isolation filter needs a native plugin.
- **Plan:** two builds that share one idea (a single on/off).

| Build | What it is | Quality | Effort | Do it |
|---|---|---|---|---|
| **B1. Script toggle** | A script that adds and switches OBS's built-in Noise Suppression filter, with a hotkey | Good to very good | Low | First |
| **B2. Plugin** | A native OBS audio filter running a speech-enhancement model | Potentially best | High | Second |

OBS already gives every filter an on/off eye icon. So the plugin needs no visible controls at all: adding it and clicking the eye is the toggle.

## 3. Build B1: Script toggle (first win)

### Steps

1. **Discovery.** Add the built-in Noise Suppression filter to a source by hand. Open its method list. Note which methods exist on your machine. Then dump its real kind id and setting keys with a tiny script (`obs_enum_filter_types`, `obs_data_get_json_pretty`, both in the verified API list). Everything below marked *recalled* gets replaced by what you dump.
2. **Script.** `isolate_voice.py` (Python or Lua both work here, because no maths is needed):
   - Property: dropdown of audio sources.
   - Property: checkbox "Isolation on".
   - Hotkey: "Toggle voice isolation" using `obs_hotkey_register_frontend`.
   - Action: create the filter on the chosen source if missing, then enable or disable it.
3. **Method choice, in this order of preference:**
   1. **NVIDIA noise removal** (recalled). Needs an NVIDIA RTX GPU and the NVIDIA Audio Effects SDK installed separately, on Windows. An RTX 3050-class laptop GPU should qualify, but confirm against NVIDIA's current requirement list. Best quality of the built-in options.
   2. **RNNoise** (recalled). CPU only, works well on steady and moderately varying noise, no extra download.
   3. **Speex** (recalled). Weakest. Fallback only.
4. **Fixed strength.** Choose one sensible strength in Phase 1 listening tests and hide it. No slider, since you asked for a single toggle.

### Failure modes and branches (B1)

| ID | Trigger | Symptom | Estimate | Branch |
|---|---|---|---|---|
| B1-1 | NVIDIA SDK not installed or GPU not supported | NVIDIA method missing or greyed out | about 30 percent on first try | Fall back to RNNoise automatically and log which method is active |
| B1-2 | GPU busy with a game and the video encoder | Audio glitches or frame drops when isolation is on | about 20 percent on a 3050-class laptop GPU | Switch to RNNoise (CPU). Compare GPU use with the toggle on and off |
| B1-3 | Method names or setting keys differ from the recalled ones | Filter created but nothing changes | about 25 percent | Use the discovery dump from step 1 |
| B1-4 | Over-suppression | Word endings clipped, "underwater" tone | about 30 percent at high strength | Lower the fixed strength; pick it from the listening test |
| B1-5 | Another noise filter already on the source | Double processing, thin sound | about 40 percent on an existing setup | Script warns and offers to disable the older one |
| B1-6 | Hotkey conflicts | Toggle does nothing | about 10 percent | Rebind in OBS Settings, Hotkeys |
| B1-7 | Python not configured in OBS | Script will not load | about 35 percent first time | Use Lua for this script, or set the Python path under Tools, Scripts |

## 4. Build B2: Native plugin (second)

### Why bother after B1

B1 is limited to what OBS ships. B2 lets us pick the model, control latency and quality, and combine isolation with App 1 inside one filter later.

### Design

- **Template:** `https://github.com/obsproject/obs-plugintemplate` (verified, GPL-2.0). Same build requirements as App 1: Visual Studio 17 2022 and CMake 3.30.5 on Windows.
- **Registration:** `obs_source_info`, type `OBS_SOURCE_TYPE_FILTER`, flag `OBS_SOURCE_AUDIO`, callback `filter_audio` (verified to exist).
- **Model candidate:** a DeepFilterNet-class speech enhancement network (recalled: full-band 48 kHz, permissive licence, real-time on CPU, ships a Rust library and a LADSPA plugin). Alternative: RNNoise code embedded directly. **Verify licence and current version before committing.**
- **Inference:** run the model on a worker thread. Audio thread only copies frames in and out of lock-free ring buffers.
- **Latency:** expect roughly 20 to 40 ms (recalled; must be measured). If it exceeds what you tolerate while monitoring yourself, use OBS's sync offset for stream audio and avoid monitoring through OBS.
- **Resampling:** the model runs at 48 kHz. If OBS runs at 44.1 kHz, resample in and out (cost and small latency).
- **Controls:** none. The filter's eye icon is the toggle. Strength is fixed at the value chosen in listening tests.
- **Failure policy:** if the worker thread falls behind, pass the input through unchanged rather than glitching, and log it once.

### Failure modes and branches (B2)

| ID | Trigger | Symptom | Estimate | Branch |
|---|---|---|---|---|
| B2-1 | Model too heavy for the laptop CPU alongside OBS and a game | Dropouts, high CPU | about 25 percent | Use a smaller model or RNNoise; or use the GPU path in B1 |
| B2-2 | Latency too high | Echo when monitoring; lip-sync drift | about 30 percent | Measure; use sync offset; disable monitoring through OBS |
| B2-3 | Model artefacts on expressive or whispered speech | Warbling, swallowed syllables | about 30 percent | Lower strength; blend dry and wet signals by a fixed ratio |
| B2-4 | Licence incompatibility | Cannot ship binary | about 10 percent | Check before coding; choose another model |
| B2-5 | OBS major release breaks the plugin | Fails to load | about 30 percent per major release | Rebuild against the new libobs; keep the inference code separate |
| B2-6 | Sample-rate switch while running | Garbled audio | about 15 percent | Rebuild resamplers and reset model state on change |
| B2-7 | Dropped frames during CPU spikes | Brief gaps | about 20 percent | Ring buffer sized for 100 ms; pass-through fallback |

## 5. Tier C (optional, later): my voice only

This is a separate project. Plan it only after A works.

- **Idea:** record 30 to 60 s of your voice once. Compute a speaker fingerprint with a small speaker-embedding model (recalled: models of this kind exist and run in tens of milliseconds). While live, compare each short segment of audio to your fingerprint and open or close a soft gate.
- **What it can do:** remove other people talking when you are not talking.
- **What it cannot do:** remove another voice while you are speaking at the same time.
- **Main risks:**
  - It rejects your own voice when you are tired, ill, whispering or shouting. Estimate: about 25 percent of the time in the first version.
  - It lets a similar voice through. Estimate: about 15 percent.
  - It adds latency of one analysis window.
- **Branch:** if your own voice is rejected more than occasionally, keep Tier A only and make Tier C a separate, optional filter.

## 6. Chain order with App 1

1. Isolation (this app)
2. Voice Match (App 1)
3. Nothing else that changes gain or dynamics. Remove OBS's own Gain, Compressor and Limiter from the same source, because Voice Match already includes them.

If the room is noisy, running Voice Match without isolation makes its learned tone curve less trustworthy. App 1's blueprint halves its correction automatically when it detects a poor speech-to-noise ratio (failure mode F3 there).

## 7. Validation framework

Evidence rule: no claim of "it works" without a saved report.

### Test recordings

Record each once with isolation off, then with isolation on, using the same raw input file for both.

| # | Scenario |
|---|---|
| 1 | Silence, 30 s (only the room) |
| 2 | Speech in a quiet room |
| 3 | Speech with a fan or air conditioner |
| 4 | Speech while typing on a keyboard |
| 5 | Speech with music at low volume |
| 6 | Speech with a TV or a second person talking |
| 7 | Whispering and shouting samples |
| 8 | Speech while a game and the video encoder are running |

### Metrics

| Metric | How | Pass |
|---|---|---|
| Noise reduction | Level of scenario 1 with isolation on versus off | at least 20 dB lower (hard for B1 and B2) |
| Speech preserved | 15-band tone profile of scenario 2, on versus off | each band within 1.5 dB (soft) |
| Word integrity | Listening, 10 sentences, count clipped starts and ends | at most 1 in 10 (soft) |
| Keyboard | Scenario 4 listening | keystrokes not audible at normal volume (soft) |
| Background voice | Scenario 6 | Tier A: expect it to remain; Tier C: at least 15 dB lower when you are silent |
| Latency | Loopback measurement or clap test against a reference | recorded; compared with your tolerance |
| CPU and GPU | Task Manager with a game running | audio chain under 5 percent CPU, no encoder drops |
| Stability | 8-hour run | zero dropouts (hard) |

Use the 15-band profile measurement from App 1's analyser for the "Speech preserved" row, so both apps are tested with the same ruler.

## 8. Estimates

All figures are estimates, not measurements.

- B1 works (any method) on the first day: about 80 percent.
- B1 with NVIDIA noise removal available and stable alongside a game: about 60 percent.
- B2 reaches parity with B1 in quality: about 55 percent.
- B2 exceeds B1 in quality in your real room: about 30 percent.
- Tier C acceptable in daily use: about 35 percent.

## 9. Scope limits for v1

- One toggle. No strength or threshold controls.
- No custom window.
- Windows first.
- No cloud processing.
- Tier C is not in v1.

## 10. Open questions

1. Is the machine with the RTX 3050 the one that runs OBS for this?
2. Which noise problems matter most: steady (fan, hum), keyboard, or other people talking?
3. Do you monitor your own voice through OBS while recording or streaming? (This decides how much latency B2 can have.)
4. Do you also run a game or other GPU-heavy app while streaming?

## 11. Next step

1. Build B1 (about an hour once discovery is done) and use it for a week as the baseline.
2. Record scenarios 1 to 8 with it and save the reports.
3. Decide from the data whether B2 is worth building.
