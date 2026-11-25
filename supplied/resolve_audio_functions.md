# Each audio function, resolved

Second reference. The first file, `resolve_audio_tools.md`, is the short map. This file is the call for each function. Source: installed `DaVinciResolveScript.pyi`, README section "Looking up Timeline item properties", and a live `GetEffectsList("audio")` / `GetNormalizeAudioModes()` read on 2026-11-24. Resolve answered. `GetFairlightPresets()` returned an empty dict, so no saved Fairlight preset names exist yet.

There is no `SetProperty`. Clip values go through `TimelineItem.SetProperties({...})` and `GetProperties()`. One bad key rejects the whole dictionary. Values outside the stated range are clipped. Keys marked active-timeline-only work only on the open timeline.

## Functions a script can set

### Gain

- Call: `item.SetProperties({"AudioVolumeEnabled": True, "AudioVolume": db})`
- Read: `item.GetProperties()["AudioVolume"]`
- Range: -100.0 to 30.0 dB
- Wrapper: `set_gain_db(item, db)` in `resolve_audio_tools.py`

### Pan

- Call: `item.SetProperties({"AudioPanEnabled": True, "AudioPan": value})`
- Range: -100.0 to 100.0

### Pitch

- `AudioPitchEnabled`, `AudioPitchSemiTones` -24.0 to 24.0, `AudioPitchCents` -100.0 to 100.0

### Voice Isolation

Two equivalent connections. Both are active-timeline-only.

- Clip state: `item.SetVoiceIsolationState({"isEnabled": True, "amount": 40})`
- Clip properties: `AudioVoiceIsolationEnabled`, `AudioVoiceIsolationAmount` 0 to 100
- Track state: `timeline.SetVoiceIsolationState(trackIndex, {"isEnabled": True, "amount": 40})`
- Read: `item.GetVoiceIsolationState()` or `timeline.GetVoiceIsolationState(trackIndex)`
- Not an effect id. It does not appear in `GetEffectsList("audio")`.

### Dialogue leveler

Active-timeline-only properties:

- `AudioDialogueLevelerEnabled`
- `AudioDialogueLevelerMode`: `resolve.DIALOGUE_LEVELER_MODE_ALLOW_WIDER_DYNAMICS`, `OPTIMIZE_MODERATE_LEVELS`, `MORE_LIFT_FOR_LOW_LEVELS`, `LIFT_SOFT_WHISPERY_SOURCES`. A read returns the number, not the name.
- `AudioDialogueLevelerReduceLoudDialogue`
- `AudioDialogueLevelerLiftSoftDialogue`
- `AudioDialogueLevelerBackgroundReduction`
- `AudioDialogueLevelerOutputGain`: 0.0 to 6.0 dB

### Level matcher

- Measure first: `item.AnalyzeAudioLevels(mode)` returns `Integrated` LUFS and `TruePeak` dBFS. -100.0 means nothing was measured. Do not pass the peak-only modes `Sample Peak Program` or `True Peak` to this call.
- Apply: `timeline.NormalizeAudioLevel([item], options)`
- `options["normalizationMode"]` must be one of the live modes below.
- `options["targetLoudness"]` is LKFS. `options["targetLevel"]` is dBFS.
- `options["setLevelMode"]` defaults to relative. Independent is `resolve.NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT`.
- Live modes: Sample Peak Program, True Peak, ITU-R BS.1770-1, ITU-R BS.1770-4, ATSC A/85, EBU R128, OP-59, TR-B32, AGCOM 219/09/CSP, Netflix, YouTube, Disney - 2.0, Disney - 5.1+, TencentVideo.

### Fades

- `item.GetFades()` and `item.SetFades({"FadeIn": frames, "FadeOut": frames})`
- Durations are frames, not milliseconds.

### Copy the audio settings that already exist

- `item.CopyAttributes(targets, {"audioVolume": True, "audioPlugins": True, "audioEqualizer": True})`
- This pastes what is already on a clip. It does not create an EQ curve from numbers.

## Functions a script can add, but not dial

`resolve.GetEffectsList("audio")` is required. The no-argument call returns video effects only. `item.AddEffect("audio", id)` adds the effect. `Effect` can then only report info, enable or disable, and change index. There is no parameter method.

| Function | Resolves to | Id |
|---|---|---|
| Equalizer | Fairlight EQ | `Audio FX/Fairlight FX/Fairlight EQ` |
| Dynamics, closest | Limiter, Multiband Compressor, Dialogue Processor, Vocal Channel | `Audio FX/Fairlight FX/` plus that name |
| Gain plugin | Gain. Prefer clip `AudioVolume` instead. | `Audio FX/Fairlight FX/Gain` |
| Level meter plugin | Loudness Meter, Meter | same prefix |
| EQ matcher | Does not resolve. No method and no effect with that name. | none |
| Voice Isolation plugin | Does not resolve. Use the state calls above. | none |

The other 29 audio ids, same prefix: Chain FX, Chorus, De-Esser, De-Hummer, Delay, Distortion, Echo, Flanger, Foley Sampler, Frequency Analyzer, LFE Filter, Modulation, Monitor, Noise Reduction, Phase Meter, Pitch, Reverb, Soft Clipper, Stereo Fixer, Stereo Width, Surround Analyzer.

## Timeline-wide only

- `resolve.GetFairlightPresets()` listed no presets on this read.
- `project.ApplyFairlightPresetToCurrentTimeline(name)` applies one saved preset to the whole current timeline. It is not a per-band writer.
