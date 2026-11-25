#!/usr/bin/env bash
# Parity check: C vmcore vs Python matcher oracle on the same WAVs.
# For each test file:
#   1. Python oracle (matcher profile + match_curve) -> oracle.json
#   2. C vmcore (ffmpeg 24k f32 pipe -> test_vmcore analyse + curve)
#   3. diff band by band; fail if any band differs > 0.05 dB or curve > 0.01
set -u
VAL="${1:-/home/z/my-project/work/val}"
PLUGIN_SRC="$(cd "$(dirname "$0")/../plugin/src" && pwd)"
BIN=/tmp/test_vmcore

gcc -O2 -std=c11 -I "$PLUGIN_SRC" -o "$BIN" \
    "$(dirname "$0")/../plugin/tests/test_vmcore.c" -lm || exit 1

fail=0
rm -f /tmp/oracle_*.json /tmp/c_profile_*.json /tmp/curve_input_*.json
for wav in "$VAL"/device_take.wav "$VAL"/headset_quiet.wav "$VAL"/hot_wide.wav; do
	name=$(basename "$wav" .wav)
	# --- oracle ---
	python3 "$VAL/matcher/match_voice.py" profile "$wav" --output "/tmp/oracle_$name.json" >/dev/null || exit 1
	# --- C analyser (same 24k f32le stream the matcher decodes internally) ---
	ch=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels \
		-of csv=p=0 "$wav")
	ffmpeg -hide_banner -nostdin -i "$wav" -ar 24000 -c:a pcm_f32le -f f32le pipe:1 \
		| "$BIN" analyse "$ch" > "/tmp/c_profile_$name.json" || exit 1
	# --- compare profiles ---
	python3 - "$name" <<'EOF' || fail=1
import json, sys
name = sys.argv[1]
oracle = json.load(open(f"/tmp/oracle_{name}.json"))
c = json.load(open(f"/tmp/c_profile_{name}.json"))
worst = 0.0
for i, (o, v) in enumerate(zip(oracle["spectrumDb"], c["spectrumDb"])):
    d = abs(o - v)
    worst = max(worst, d)
    if d > 0.05:
        print(f"  BAND MISMATCH {name} band {i}: oracle {o} vs C {v}")
d70 = abs(oracle["speechRms70"] - c["speechRms70"])
dsp = abs(oracle["speechSpread"] - c["speechSpread"])
ok = worst <= 0.05 and d70 <= 0.05 and dsp <= 0.05
print(f"  {name}: worst band {worst:.3f} dB, rms70 {d70:.3f}, spread {dsp:.3f} -> {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
EOF
	# --- curve parity: python oracle curve on oracle profile vs on C profile ---
	python3 - "$name" "/tmp/oracle_$name.json" <<'EOF' > "/tmp/curve_input_$name.json"
import json, sys
name, oracle_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, "/home/z/my-project/work/val/matcher")
import match_voice
oracle = json.load(open(oracle_path))
ref = json.load(open("/home/z/my-project/work/val/ref.json"))
curve = match_voice.match_curve(oracle, ref)
c = json.load(open(f"/tmp/c_profile_{name}.json"))
src = {"sampleRate": 48000, "spectrumDb": c["spectrumDb"],
       "speechRms70": c["speechRms70"], "speechSpread": c["speechSpread"]}
ccurve = match_voice.match_curve(src, ref)
worst = max(abs(curve[k] - ccurve[k]) for k in curve)
ok = worst <= 0.01
print(json.dumps({"oracle_curve": curve, "c_curve": ccurve, "worst": worst, "ok": ok}))
sys.exit(0 if ok else 1)
EOF
	if [ $? -ne 0 ]; then fail=1; fi
	python3 -c "
import json
name='$name'
d=json.load(open(f'/tmp/curve_input_{name}.json'))
print(f\"  curve {name}: worst {d['worst']:.3f} -> {'PASS' if d['ok'] else 'FAIL'}\")
print(f\"    oracle {d['oracle_curve']}\")
print(f\"    C      {d['c_curve']}\")
" || fail=1
done
echo "-----"
[ "$fail" -eq 0 ] && echo "PARITY: ALL PASS" || echo "PARITY: FAILURES PRESENT"
exit $fail
