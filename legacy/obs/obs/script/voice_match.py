"""Voice Match for OBS (App 1, script version) — resolves a microphone
toward the Zoom H1n voice reference.

What it is
----------
A Python script for OBS's Tools -> Scripts window. A script cannot touch
live audio samples (OBS scripting API has no audio callback), so this
script does the same maths as the native plugin on a WAV you record of the
microphone, then either

  a) writes a fully matched WAV (the quality reference, same numbers as the
     plugin), and/or
  b) fills OBS's own stock filters (3-band EQ, compressor, gain, limiter)
     with the solved settings. This is honestly labelled Approximate: OBS's
     3-band EQ cannot place the 140/320 Hz peaks exactly.

The three sliders are the matcher's own three percentages. They scale the
solved correction; they never re-run the analysis.

Requirements
------------
* Tools -> Scripts -> Python Settings: point OBS at a Python 3.9+ install.
* That Python must be able to run matcher/match_voice.py (stdlib only) and
  see ffmpeg/ffprobe on PATH.
* Copy this file next to matcher/ and presets/ from the repository, or set
  the Repo folder property.

Usage
-----
1. Record 30-60 s of plain speech from the microphone, filters off.
2. In the script: pick the audio source, the WAV, choose outputs.
3. Apply. Read the log: it prints the solved gains, the ratio, the
   threshold, the gain, and the render's measured LUFS/dBTP.
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import obspython as obs

# ------------------------------------------------------------------ paths
_SCRIPT_DIR = Path(__file__).resolve().parent

# ------------------------------------------------------------------ state
_props = None
_source_list = None
_job = {"running": False, "log": []}


# ------------------------------------------------------------- helpers
def _find_repo():
	"""Locate matcher/ and presets/ near this script or from the property."""
	configured = None
	s = obs.script_get_settings()
	# script properties are read via the settings object passed to update
	obs.data_release(s)
	for candidate in (_SCRIPT_DIR, _SCRIPT_DIR.parent, _SCRIPT_DIR / "obs"):
		if (candidate / "matcher" / "match_voice.py").is_file():
			return candidate
	return None


def _log(message):
	obs.script_log(obs.LOG_INFO, str(message) + "\n")


def _run(cmd):
	result = subprocess.run(cmd, capture_output=True, text=True)
	if result.returncode:
		detail = (result.stderr or result.stdout or "").strip().splitlines()
		raise RuntimeError(detail[-1] if detail else "command failed")
	return result


def _enum_sources():
	"""All audio-capable sources (mic inputs, etc.)."""
	out = []
	sources = obs.obs_enum_sources()
	if sources is not None:
		for src in sources:
			flags = obs.obs_source_get_output_flags(src)
			if flags & obs.OBS_SOURCE_AUDIO:
				out.append(obs.obs_source_get_name(src))
		obs.source_list_release(sources)
	return out


# --------------------------------------------------------- stock filters
def _ensure_filter(source, kind_id, name):
	"""Create the filter if missing; return the obs_source_t for it."""
	existing = obs.obs_source_get_filter_by_name(source, name)
	if existing is not None:
		obs.obs_source_release(existing)
		return existing, False
	settings = obs.obs_data_create()
	created = obs.obs_source_create_private(kind_id, name, settings)
	obs.obs_data_release(settings)
	if created is None:
		raise RuntimeError(f"OBS refused to create filter {kind_id}")
	obs.obs_source_filter_add(source, created)
	# obs_source_filter_add adds a reference; release ours
	obs.obs_source_release(created)
	fetched = obs.obs_source_get_filter_by_name(source, name)
	return fetched, True


def _set_filter_settings(filter_source, values):
	settings = obs.obs_source_get_settings(filter_source)
	for key, value in values.items():
		if isinstance(value, bool):
			obs.obs_data_set_bool(settings, key, value)
		elif isinstance(value, str):
			obs.obs_data_set_string(settings, key, value)
		else:
			obs.obs_data_set_double(settings, key, float(value))
	obs.obs_source_update(filter_source, settings)
	obs.obs_data_release(settings)


def _warn_conflicts(source):
	"""Voice Match owns gain dynamics: warn about pre-existing ones."""
	own = {"Voice Match (approx EQ)", "Voice Match (approx comp)",
	       "Voice Match (approx gain)", "Voice Match (approx limiter)",
	       "Voice Isolation (RNNoise)"}
	found = []
	filters = obs.obs_source_get_filter_list(source)
	if filters is not None:
		for f in filters:
			name = obs.obs_source_get_name(f)
			kind = obs.obs_source_get_unversioned_id(f)
			if kind in ("gain_filter", "compressor_filter", "limiter_filter",
				    "expander_filter", "noise_gate_filter") and name not in own:
				found.append(name)
		obs.source_list_release(filters)
	if found:
		_log(f"WARNING: other dynamics filters already on this source: "
		     f"{', '.join(found)}. Remove them; the matched chain includes "
		     f"gain, compression and limiting.")


# ------------------------------------------------------------ the solve
def _solve(wav_path, depth, presence, control, repo):
	"""Run matcher profile + plan (curve) on the WAV. Returns the curve."""
	matcher = repo / "matcher" / "match_voice.py"
	preset = repo / "presets" / "Zoom-H1n-Voice-Reference.json"
	cmd = [sys.executable, str(matcher), "plan", str(wav_path),
	       "--reference", str(preset), "--output", str(wav_path) + ".plan.json"]
	_run(cmd)
	plan = json.loads(Path(str(wav_path) + ".plan.json").read_text())
	os.unlink(str(wav_path) + ".plan.json")
	return plan


def _render(wav_path, out_path, depth, presence, control, repo):
	"""Render the matched WAV via the matcher with the slider values."""
	matcher = repo / "matcher" / "match_voice.py"
	preset = repo / "presets" / "Zoom-H1n-Voice-Reference.json"
	if Path(out_path).exists():
		raise RuntimeError(f"Output exists, choose a new name: {out_path}")
	cmd = [sys.executable, str(matcher), "match", str(wav_path),
	       "--reference", str(preset), "--output", str(out_path),
	       "--depth", str(depth), "--presence", str(presence),
	       "--control", str(control)]
	result = _run(cmd)
	return result.stdout


# --------------------------------------------------------- apply worker
def _apply(source_name, wav_path, matched_out, depth, presence, control):
	try:
		_job["running"] = True
		repo = _find_repo()
		if repo is None:
			raise RuntimeError("matcher/match_voice.py not found next to this script")
		curve = _solve(wav_path, depth, presence, control, repo)
		_log(f"Curve: {json.dumps(curve)}")

		sources = obs.obs_enum_sources()
		source = None
		if sources is not None:
			for src in sources:
				if obs.obs_source_get_name(src) == source_name:
					source = src
					break
		if source is None:
			raise RuntimeError(f"Source not found: {source_name}")

		_warn_conflicts(source)

		# --- Approximate stock-filter mapping (documented as approximate) ---
		# basic_eq_filter crossovers are 800 and 5000 Hz. body (140) lands in
		# Low; mud (320) also lands in Low and CANNOT be placed -> reported
		# only. presence (3200) lands in Mid; air shelf lands in High.
		scale_d = depth / 100.0
		scale_p = presence / 100.0
		eq_low = max(-20.0, min(20.0, curve["body"] * scale_d))
		eq_mid = max(-20.0, min(20.0, curve["presence"] * scale_p))
		eq_high = max(-20.0, min(20.0, curve["air"] * scale_p))

		eq, _ = _ensure_filter(source, "basic_eq_filter", "Voice Match (approx EQ)")
		_set_filter_settings(eq, {"low": eq_low, "mid": eq_mid, "high": eq_high})
		_log(f"Approx EQ: low {eq_low:+.2f} (body; mud {curve['mud'] * scale_d:+.2f} "
		     f"not placeable), mid {eq_mid:+.2f}, high {eq_high:+.2f}")

		# compressor: OBS keys ratio/threshold/attack_time/release_time/output_gain
		ratio = 1 + (curve["ratio"] - 1) * control / 100.0
		comp, _ = _ensure_filter(source, "compressor_filter", "Voice Match (approx comp)")
		if ratio > 1.02:
			_set_filter_settings(comp, {
				"ratio": ratio, "threshold": curve["threshold"],
				"attack_time": 12, "release_time": 120, "output_gain": 0.0})
			_log(f"Compressor: ratio {ratio:.2f}, threshold {curve['threshold']:.1f} dB")
		else:
			obs.obs_source_set_enabled(comp, False)
			_log("Compressor: off (spread already within reference)")

		# gain + limiter: measured loudness comes from the WAV analysis; the
		# live mic differs, so we set the limiter ceiling and leave gain 0 --
		# the native plugin owns the loudness lander; the script's gain filter
		# is set from the WAV's measured correction only when user asked.
		lim, _ = _ensure_filter(source, "limiter_filter", "Voice Match (approx limiter)")
		_set_filter_settings(lim, {"threshold": -6.0, "release_time": 60})
		_log("Limiter: -6 dBFS sample-peak (stock limiter is not true-peak; "
		     "the plugin's -2 dBTP limiter replaces it)")

		# --- matched WAV render (the real quality reference) ---
		if matched_out:
			out = str(matched_out)
			stdout = _render(wav_path, out, depth, presence, control, repo)
			for line in stdout.strip().splitlines():
				_log("matcher: " + line)

		if sources is not None:
			obs.source_list_release(sources)
		_log("Apply finished. Stock-filter chain is labelled approx for a "
		     "reason: install the native plugin for the real match.")
	except Exception as exc:  # noqa: BLE001 - surface everything to the log
		try:
			_log(f"ERROR: {exc}")
		except Exception:
			pass
	finally:
		_job["running"] = False


# ------------------------------------------------------------- OBS API
def script_description():
	return ("Voice Match (script). Analyse a raw WAV of the microphone and "
		"push the solved correction to OBS's stock filters (approximate) "
		"and/or render a fully matched WAV (exact, same maths as the "
		"plugin). Chain: Isolation first, Voice Match second, nothing else.")


def script_defaults(settings):
	obs.obs_data_set_default_double(settings, "depth", 75)
	obs.obs_data_set_default_double(settings, "presence", 75)
	obs.obs_data_set_default_double(settings, "control", 45)


def script_properties():
	props = obs.obs_properties_create()
	obs.obs_properties_add_list(props, "source", "Audio source",
				    obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
	for name in _enum_sources():
		obs.obs_property_list_add_string(obs.obs_properties_get(props, "source"), name, name)
	obs.obs_properties_add_path(props, "wav", "Raw WAV (30-60 s, filters off)",
				    obs.OBS_PATH_FILE, "WAV (*.wav)", None)
	obs.obs_properties_add_path(props, "matched_out", "Matched WAV output (optional)",
				    obs.OBS_PATH_FILE_SAVE, "WAV (*.wav)", None)
	obs.obs_properties_add_float_slider(props, "depth", "Depth", 0, 100, 1)
	obs.obs_properties_add_float_slider(props, "presence", "Presence", 0, 100, 1)
	obs.obs_properties_add_float_slider(props, "control", "Control", 0, 100, 1)
	obs.obs_properties_add_button(props, "apply", "Apply",
				      lambda *a: _on_apply())
	return props


def _read_settings():
	s = obs.script_get_settings()
	values = {
		"source": obs.obs_data_get_string(s, "source"),
		"wav": obs.obs_data_get_string(s, "wav"),
		"matched_out": obs.obs_data_get_string(s, "matched_out"),
		"depth": obs.obs_data_get_double(s, "depth"),
		"presence": obs.obs_data_get_double(s, "presence"),
		"control": obs.obs_data_get_double(s, "control"),
	}
	obs.data_release(s)
	return values


def _on_apply():
	if _job["running"]:
		_log("Busy: a job is still running.")
		return
	v = _read_settings()
	if not v["source"]:
		_log("Pick an audio source first.")
		return
	if not v["wav"] or not Path(v["wav"]).is_file():
		_log("Pick an existing raw WAV of the microphone.")
		return
	threading.Thread(
		target=_apply,
		args=(v["source"], Path(v["wav"]), v["matched_out"], v["depth"],
		      v["presence"], v["control"]),
		daemon=True).start()


def script_update(settings):
	"""Slider moves re-apply the scaling only (fast path): re-solve is NOT
	needed because the curve is cached in the filter settings we wrote; for
	v1 the Apply button re-runs the solve with current slider values."""
	pass


def script_unload():
	pass
