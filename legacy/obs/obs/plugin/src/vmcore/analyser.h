/* vmcore analyser.h — exact port of matcher's profile()/speech_frames():
 * 24 kHz analysis rate, 2048-point Hann, STEP 4096 streaming read, reservoir
 * of 240 frames with random.Random(16), gate max(-65, P90-18, P99-27),
 * 15 half-octave bands (first edge 100/sqrt(1.4), geometric means, last edge
 * 11900), power-summed across channels, per-frame normalised, averaged, dB.
 */
#ifndef VMCORE_ANALYSER_H
#define VMCORE_ANALYSER_H

#include "fft.h"
#include "rng.h"

#define VM_BANDS 15
#define VM_MAX_FRAMES 240
#define VM_ANALYSIS_RATE 24000
#define VM_STEP 4096
#define VM_GATE_MIN (-65.0)
#define VM_GATE_P90 18.0
#define VM_GATE_P99 27.0

typedef struct {
	int sample_rate;
	int channels;
	double loudness;      /* LUFS from OBS K-meter or offline ebur128 */
	double true_peak;     /* dBTP */
	double speech_rms70;  /* dBFS */
	double speech_spread; /* dB */
	double spectrum_db[VM_BANDS];
} vm_profile;

typedef struct {
	double level_db;
	float samples[VM_FFT_SIZE * 2]; /* up to 2 channels; mono uses [0..2048) */
	int channels;
} vm_frame;

typedef struct {
	vm_frame frames[VM_MAX_FRAMES];
	int count;        /* reservoir fill level (<= MAX) */
	int seen;         /* total frames seen */
	vm_rng rng;
	vm_fft fft;
	/* band integration state */
	double band_sums[VM_BANDS];
	int used_frames;  /* gated frames accumulated into band_sums */
	double gated_levels[VM_MAX_FRAMES];
	int gated_count;
	double loudness; /* externally supplied */
	double true_peak;
} vm_analyser;

static const double vm_bands_hz[VM_BANDS] = {100, 140, 200, 280, 400, 560, 800,
					     1120, 1600, 2240, 3200, 4480, 6400, 9000, 10900};

static void vm_analyser_init(vm_analyser *a, uint32_t seed)
{
	a->count = 0;
	a->seen = 0;
	vm_rng_init(&a->rng, seed);
	vm_fft_setup(&a->fft);
	for (int i = 0; i < VM_BANDS; i++)
		a->band_sums[i] = 0.0;
	a->used_frames = 0;
	a->gated_count = 0;
	a->loudness = -70.0;
	a->true_peak = -70.0;
}

/* Feed one STEP-sized block (matcher's streaming read semantics: a frame is
 * the FIRST FFT_SIZE samples of each 4096-sample chunk). block: interleaved
 * floats, STEP*channels samples. The caller must already have resampled to
 * 24 kHz for analysis parity; live use also feeds 24k-downsampled audio.
 */
static void vm_analyser_push(vm_analyser *a, const float *block, int channels)
{
	a->seen++;
	double energy = 0.0;
	int n = VM_FFT_SIZE * channels;
	for (int i = 0; i < n; i++)
		energy += (double)block[i] * block[i];
	energy /= (double)n;
	double level_db = 10.0 * log10(energy > 1e-12 ? energy : 1e-12);

	vm_frame *slot;
	if (a->count < VM_MAX_FRAMES) {
		slot = &a->frames[a->count++];
	} else {
		uint32_t pick = vm_rng_randbelow(&a->rng, (uint32_t)a->seen);
		if (pick >= (uint32_t)VM_MAX_FRAMES)
			return; /* frame not kept */
		slot = &a->frames[pick];
	}
	slot->level_db = level_db;
	slot->channels = channels;
	for (int i = 0; i < n; i++)
		slot->samples[i] = block[i];
}

static int vm_cmp_double(const void *x, const void *y)
{
	double a = *(const double *)x, b = *(const double *)y;
	return (a > b) - (a < b);
}

static double vm_percentile(double *sorted, int n, double fraction)
{
	double index = (n - 1) * fraction;
	int lower = (int)index;
	int upper = lower + 1 < n ? lower + 1 : n - 1;
	return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - (double)lower);
}

/* Compute the gated statistics and spectrum. Call once after feeding.
 * Returns 0 on success, -1 if too little speech (gated < 4).
 */
static int vm_analyser_finish(vm_analyser *a, vm_profile *out)
{
	if (a->count == 0)
		return -1;
	double levels[VM_MAX_FRAMES];
	for (int i = 0; i < a->count; i++)
		levels[i] = a->frames[i].level_db;
	qsort(levels, a->count, sizeof(double), vm_cmp_double);
	double gate = vm_percentile(levels, a->count, 0.90) - VM_GATE_P90;
	double g2 = vm_percentile(levels, a->count, 0.99) - VM_GATE_P99;
	if (g2 > gate)
		gate = g2;
	if (VM_GATE_MIN > gate)
		gate = VM_GATE_MIN;

	/* integrate bands over gated frames */
	static double power[VM_FFT_HALF];
	double band_edges[VM_BANDS + 1];
	band_edges[0] = vm_bands_hz[0] / sqrt(1.4);
	for (int i = 0; i < VM_BANDS - 1; i++)
		band_edges[i + 1] = sqrt(vm_bands_hz[i] * vm_bands_hz[i + 1]);
	band_edges[VM_BANDS] = 11900.0;

	double bins_per_hz = (double)VM_FFT_SIZE / (double)VM_ANALYSIS_RATE;
	int used = 0;
	double gated[VM_MAX_FRAMES];
	int gated_count = 0;
	for (int f = 0; f < a->count; f++) {
		if (a->frames[f].level_db < gate)
			continue;
		gated[gated_count++] = a->frames[f].level_db;
		double band_energy[VM_BANDS];
		for (int b = 0; b < VM_BANDS; b++)
			band_energy[b] = 0.0;
		for (int ch = 0; ch < a->frames[f].channels; ch++) {
			vm_fft_channel(&a->fft, a->frames[f].samples, a->frames[f].channels, ch, power);
			for (int b = 0; b < VM_BANDS; b++) {
				int lo = (int)ceil(band_edges[b] * bins_per_hz);
				int hi = (int)ceil(band_edges[b + 1] * bins_per_hz);
				if (hi > VM_FFT_HALF)
					hi = VM_FFT_HALF;
				for (int k = lo; k < hi; k++)
					band_energy[b] += power[k];
			}
		}
		double total = 0.0;
		for (int b = 0; b < VM_BANDS; b++)
			total += band_energy[b];
		if (total < 1e-12)
			total = 1e-12;
		for (int b = 0; b < VM_BANDS; b++)
			a->band_sums[b] += band_energy[b] / total;
		used++;
	}
	if (gated_count < 4)
		return -1;

	qsort(gated, gated_count, sizeof(double), vm_cmp_double);
	for (int b = 0; b < VM_BANDS; b++) {
		double v = a->band_sums[b] / (double)used;
		out->spectrum_db[b] = 10.0 * log10(v > 1e-10 ? v : 1e-10);
	}
	out->speech_rms70 = vm_percentile(gated, gated_count, 0.70);
	out->speech_spread = vm_percentile(gated, gated_count, 0.90) -
			     vm_percentile(gated, gated_count, 0.20);
	out->loudness = a->loudness;
	out->true_peak = a->true_peak;
	out->sample_rate = VM_ANALYSIS_RATE;
	out->channels = 2;
	(void)levels;
	return 0;
}

#endif
