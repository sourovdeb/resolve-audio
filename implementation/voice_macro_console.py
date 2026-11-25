"""Match a Resolve audio clip to the bundled numerical voice reference.

Run: py -3 voice_macro_console.py
Or:  py -3 voice_macro_console.py --input "C:\\recordings\\voice.wav"
Requires Python, FFmpeg, and ffprobe. Resolve is optional for WAV output.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import sys

from matcher import match_voice


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "presets" / "Zoom-H1n-Voice-Reference.json"


def resolve_connection():
    existing = globals().get("resolve")
    if existing is not None:
        return existing
    try:
        import DaVinciResolveScript as scripting
    except ImportError:
        program_data = os.environ.get("PROGRAMDATA")
        if not program_data:
            return None
        modules = Path(program_data) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Developer" / "Scripting" / "Modules"
        if not modules.is_dir():
            return None
        sys.path.insert(0, str(modules))
        try:
            import DaVinciResolveScript as scripting
        except ImportError:
            return None
    return scripting.scriptapp("Resolve")


def active_clip(resolve_app, track, clip_number):
    project = resolve_app.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        raise ValueError("Open a Resolve project and timeline, or pass --input WAV.")
    found = []
    count = timeline.GetTrackCount("audio")
    for track_number in range(1, count + 1):
        if track is not None and track_number != track:
            continue
        for number, item in enumerate(timeline.GetItemListInTrack("audio", track_number) or [], 1):
            if clip_number is not None and number != clip_number:
                continue
            found.append((track_number, number, item))
    if not found:
        raise ValueError("No audio clip matched the chosen track and clip number.")
    if len(found) == 1:
        selection = found[0]
    elif sys.stdin.isatty():
        for position, (track_number, number, _) in enumerate(found, 1):
            print(f"{position}. Audio track {track_number}, clip {number}")
        position = int(input("Choose a clip number from this list: "))
        if position < 1 or position > len(found):
            raise ValueError("Choose a number shown in the list.")
        selection = found[position - 1]
    else:
        raise ValueError("Several clips exist. Pass --track and --clip, or --input WAV.")
    media = selection[2].GetMediaPoolItem()
    path = media.GetClipProperty("File Path") if media else None
    if not isinstance(path, str) or not Path(path).is_file() or Path(path).suffix.lower() != ".wav":
        raise ValueError("This clip has no linked WAV source. Pass --input with an exported WAV.")
    return Path(path), project, timeline, selection[2]


def output_name(source):
    candidate = source.with_name(source.stem + "-VoiceMacro.wav")
    number = 2
    while os.path.lexists(candidate):
        candidate = source.with_name(f"{source.stem}-VoiceMacro-{number}.wav")
        number += 1
    return candidate


def linked_helper(path):
    candidates = [Path(path)] if path else []
    configured = os.environ.get("RESOLVE_AUDIO_TOOLS")
    if configured:
        candidates.append(Path(configured))
    candidates.append(ROOT / "resolve_audio_tools.py")
    for candidate in candidates:
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("resolve_audio_tools", str(candidate))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


def match_level_on_clip(item, reference, helper_path):
    measured = item.AnalyzeAudioLevels("ITU-R BS.1770-4")
    if not isinstance(measured, dict):
        raise ValueError("Resolve could not measure this clip.")
    loudness = float(measured.get("Integrated", -100))
    peak = float(measured.get("TruePeak", -100))
    if loudness <= -99 or peak <= -99:
        raise ValueError("Resolve returned no clip loudness or true peak.")
    properties = item.GetProperties()
    previous_gain = float(properties.get("AudioVolume", 0))
    change = min(reference["loudness"] - loudness, 9.0, -2.0 - peak)
    proposed = max(-100.0, min(30.0, previous_gain + change))
    helper = linked_helper(helper_path)
    if helper and callable(getattr(helper, "set_gain_db", None)):
        applied = helper.set_gain_db(item, proposed)
    else:
        applied = item.SetProperties({"AudioVolumeEnabled": True, "AudioVolume": proposed})
    if applied is False:
        raise ValueError("Resolve rejected the new clip gain.")
    actual = item.GetProperties()
    if abs(float(actual.get("AudioVolume", -100)) - proposed) > 0.11:
        raise ValueError("Resolve did not confirm the gain setting.")
    print(f"Clip gain: {previous_gain:.2f} -> {proposed:.2f} dB. No WAV was rendered.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="target WAV. If omitted, choose a linked Resolve timeline clip")
    parser.add_argument("--reference", type=Path, default=REFERENCE, help="reference profile JSON")
    parser.add_argument("--output", type=Path, help="new WAV filename")
    parser.add_argument("--track", type=int, help="Resolve audio track number")
    parser.add_argument("--clip", type=int, help="clip number within the audio track")
    parser.add_argument("--mode", choices=("voice", "eq", "level"), default="voice")
    parser.add_argument("--loudness", choices=("reference", "youtube", "keep"), default="reference")
    parser.add_argument("--resolve-level", action="store_true", help="set clip gain through Resolve instead of rendering")
    parser.add_argument("--tools", help="optional path to your resolve_audio_tools.py helper")
    parser.add_argument("--no-import", action="store_true", help="skip Media Pool import")
    args = parser.parse_args(argv)
    try:
        tools = match_voice.media_tools() if not args.resolve_level else (None, None)
        reference = match_voice.read_reference(tools, args.reference.resolve(), True)
        resolve_app = resolve_connection()
        item = project = None
        if args.input:
            source = args.input.resolve()
            if resolve_app:
                project = resolve_app.GetProjectManager().GetCurrentProject()
        elif resolve_app:
            source, project, _, item = active_clip(resolve_app, args.track, args.clip)
        elif sys.stdin.isatty():
            source = Path(input("Target WAV path: ").strip().strip('"')).resolve()
        else:
            raise ValueError("Pass --input WAV, or run while Resolve is open.")

        if args.resolve_level:
            if item is None:
                raise ValueError("--resolve-level requires a linked Resolve timeline clip.")
            match_level_on_clip(item, reference, args.tools)
            return 0

        destination = args.output.resolve() if args.output else output_name(source)
        command = ["match", str(source), "--reference", str(args.reference.resolve()),
                   "--output", str(destination), "--mode", args.mode, "--loudness", args.loudness]
        if match_voice.main(command):
            return 1
        print(f"Created: {destination}")
        if project and not args.no_import:
            if not project.GetMediaPool().ImportMedia([str(destination)]):
                print("Import the matched WAV through Resolve's Media Pool.")
            else:
                print("Imported into Resolve's Media Pool. Replace the source clip after listening.")
        return 0
    except (OSError, ValueError, TypeError, ImportError) as exc:
        print(f"VoiceMacro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
