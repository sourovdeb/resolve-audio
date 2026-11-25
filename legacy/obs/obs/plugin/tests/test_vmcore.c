/* vmcore test: parity with matcher/match_voice.py.
 *
 * Reads a WAV (any format ffmpeg-free: PCM16/24/32 and float via a tiny
 * built-in reader for 16/24-bit and f32), feeds the analyser exactly like
 * matcher's speech_frames (24 kHz resample via a windowed-sinc resampler is
 * NOT implemented here — the test harness pipes pre-resampled f32 from
 * ffmpeg: see tools/parity_check.sh). Prints the profile as JSON and the
 * solved curve as JSON, for diffing against the Python oracle output.
 *
 * Also unit-tests the limiter: full-scale sine and burst inputs must come
 * out at or below the ceiling, exactly.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "vmcore/vmcore.h"

/* Read f32le raw from stdin: interleaved, 24000 Hz, given channel count. */
int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: %s analyse <channels>  (f32le 24k on stdin)\n"
				"       %s curve <source.json> <reference.json>\n"
				"       %s limiter\n",
			argv[0], argv[0], argv[0]);
		return 2;
	}
	if (strcmp(argv[1], "analyse") == 0) {
		int channels = atoi(argv[2]);
		vm_analyser a;
		vm_analyser_init(&a, 16);
		static float block[VM_STEP * 2];
		size_t need = (size_t)VM_STEP * (size_t)channels;
		/* Pipes deliver partial reads; loop until the block is full. */
		for (;;) {
			size_t have = 0;
			while (have < need) {
				size_t got = fread(block + have, sizeof(float), need - have, stdin);
				if (got == 0)
					break;
				have += got;
			}
			if (have < need)
				break;
			vm_analyser_push(&a, block, channels);
		}
		/* tail: matcher ignores a short final chunk; so do we */
		vm_profile p;
		if (vm_analyser_finish(&a, &p) != 0) {
			fprintf(stderr, "too little speech\n");
			return 1;
		}
		printf("{\"spectrumDb\":[");
		for (int i = 0; i < VM_BANDS; i++)
			printf("%.3f%s", p.spectrum_db[i], i + 1 < VM_BANDS ? "," : "");
		printf("],\"speechRms70\":%.2f,\"speechSpread\":%.2f}\n",
		       p.speech_rms70, p.speech_spread);
		return 0;
	}
	if (strcmp(argv[1], "curve") == 0) {
		/* stdin: JSON of {"source":{...},"reference":{...}} produced by
		 * tools/parity_check.sh from the oracle outputs */
		char buf[65536];
		size_t n = fread(buf, 1, sizeof(buf) - 1, stdin);
		buf[n] = 0;
		/* minimal JSON extraction for our fixed key layout */
		vm_profile src, ref;
		memset(&src, 0, sizeof(src));
		memset(&ref, 0, sizeof(ref));
		src.sample_rate = ref.sample_rate = 48000;
		double *targets[] = {src.spectrum_db, ref.spectrum_db};
		const char *keys[] = {"\"src\":[", "\"ref\":["};
		for (int t = 0; t < 2; t++) {
			const char *p = strstr(buf, keys[t]);
			if (!p) {
				fprintf(stderr, "missing %s\n", keys[t]);
				return 1;
			}
			p += strlen(keys[t]);
			for (int i = 0; i < VM_BANDS; i++)
				targets[t][i] = strtod(p, (char **)&p);
		}
		double s70, spread;
		const char *q = strstr(buf, "\"s70\":");
		s70 = q ? strtod(q + 6, NULL) : -20;
		q = strstr(buf, "\"spread\":");
		spread = q ? strtod(q + 9, NULL) : 12;
		src.speech_rms70 = s70;
		src.speech_spread = spread;
		vm_reference_profile(&ref);
		vm_curve c = vm_match_curve(&src, &ref);
		printf("{\"body\":%.2f,\"mud\":%.2f,\"presence\":%.2f,\"air\":%.2f,"
		       "\"threshold\":%.1f,\"ratio\":%.2f}\n",
		       c.body, c.mud, c.presence, c.air, c.threshold, c.ratio);
		return 0;
	}
	if (strcmp(argv[1], "limiter") == 0) {
		/* generate 1 s 48k stereo test signals, limit, assert ceiling */
		int fs = 48000, n = fs;
		static float left[48000], right[48000];
		float *planes[2] = {left, right};
		static double env[48000];
		double ceiling = pow(10.0, -2.0 / 20.0);
		int fails = 0;
		const char *names[] = {"sine 0.99", "sine 1.26", "sine 5k", "burst"};
		double peaks[] = {0.99, 1.26, 0.99};
		for (int t = 0; t < 4; t++) {
			vm_limiter lim;
			vm_limiter_init(&lim, 2, fs, -2.0, 5.0, 60.0);
			if (t < 3) {
				double f = t == 2 ? 5000.0 : 220.0;
				for (int i = 0; i < n; i++) {
					left[i] = right[i] =
						(float)(peaks[t] * sin(2 * M_PI * f * i / fs));
				}
			} else {
				memset(left, 0, sizeof(left));
				memset(right, 0, sizeof(right));
				for (int i = 1000; i < 1300; i++)
					left[i] = right[i] = (float)1.5 * ((i % 7) - 3) / 3.0f;
			}
			/* process in 1024-frame blocks like OBS */
			for (int off = 0; off < n; off += 1024) {
				int frames = n - off < 1024 ? n - off : 1024;
				float *pl[2] = {left + off, right + off};
				vm_limiter_envelope(&lim, pl, frames, env + off);
				vm_limiter_process(&lim, pl, frames, env + off);
			}
			double mx = 0;
			for (int i = 0; i < n; i++) {
				double a = fabs(left[i]);
				if (a > mx)
					mx = a;
			}
			double over_db = 20 * log10(mx / ceiling + 1e-30);
			int ok = mx <= ceiling + 1e-9;
			printf("%-10s peak %.6f  ceiling %.6f  %s (%+.3f dB vs ceiling)\n",
			       names[t], mx, ceiling, ok ? "PASS" : "FAIL", over_db);
			if (!ok)
				fails++;
			vm_limiter_free(&lim);
		}
		return fails ? 1 : 0;
	}
	fprintf(stderr, "unknown mode\n");
	return 2;
}
