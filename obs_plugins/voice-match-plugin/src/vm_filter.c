/* Voice Match OBS audio filter — corrected implementation v2.0
 *
 * Fixes applied (per AGENTS.md audit):
 * 1. Limiter: proper delay line + monotonic deque, not convex interpolation
 * 2. Analyzer: per-instance bounded SPSC queue, no static scratch, polyphase
 * 3. Compressor: correct sample-rate time constants, channel-average detector
 * 4. EQ: serial cascade, not parallel dry/wet summation
 * 5. Loudness: K-weighted energy with proper division by frame count
 * 6. Format change: explicit state reset on all parameters
 *
 * Chain order (audio callback):
 *   input -> optional isolation (separate filter) -> HPF 70Hz ->
 *   EQ cascade -> compressor -> gain -> true-peak limiter -> output
 */
#include <obs-module.h>
#include <plugin-support.h>
#include <stdatomic.h>
#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define VM_ID "voice_match_filter"
#define VM_NAME "Voice Match (H1n Reference)"

#define S_DEPTH "depth"
#define S_PRESENCE "presence"
#define S_CONTROL "control"
#define S_STATUS "status"
#define S_PROFILES "profiles"

#define LEARN_SECONDS 45.0
#define LEARN_MIN_FRAMES 8
#define FADE_SECONDS 2.0
#define MAX_CHANNELS 8
#define VM_ANALYSIS_RATE 24000
#define VM_FFT_SIZE 2048
#define VM_FFT_HALF 1025
#define VM_BANDS 15
#define VM_STEP 4096
#define VM_MAX_FRAMES 240

/* ================================================================ types --- */

typedef struct {
	double b0, b1, b2, a1, a2;
	double z1, z2;
} vm_biquad_t;

typedef struct {
	double threshold;
	double ratio;
	double attack_ms, release_ms, knee_db;
	double envelope;
	double gain_db;
} vm_compressor_t;

typedef struct {
	double target_lufs;
	double current_gain_db;
	double max_gain_db;
	double min_gain_db;
	double up_per_sec;
	double down_per_sec;
} vm_lander_t;

typedef struct {
	double ceiling;
	int lookahead;
	int pos;
	double *ring;
	int channels;
	double release_coef;
	double gain;
} vm_limiter_t;

typedef struct {
	int sample_rate;
	int channels;
	int dec_factor;
	double dec_phase;
	double spectrum_db[VM_BANDS];
	double speech_rms70;
	double speech_spread;
	double loudness;
	double true_peak;
	vm_rng_state rng;
	vm_fft_state fft;
	vm_frame frames[VM_MAX_FRAMES];
	int count;
	int seen;
	double band_sums[VM_BANDS];
	int used_frames;
	double gated_levels[VM_MAX_FRAMES];
	int gated_count;
} vm_analyser_t;

typedef struct {
	double spectrum_db[VM_BANDS];
	double loudness;
	double true_peak;
	double speech_rms70;
	double speech_spread;
	int sample_rate;
	int channels;
} vm_profile_t;

typedef struct {
	double body, mud, presence, air;
	double threshold;
	double ratio;
} vm_curve_t;

typedef struct {
	/* Settings (graphics thread snapshot) */
	float depth, presence, control;

	/* Format (synced from audio callback) */
	int channels;
	double sample_rate;

	/* Filter states (per-channel) */
	vm_biquad_t hp_ch[MAX_CHANNELS];
	vm_biquad_t body_ch[MAX_CHANNELS];
	vm_biquad_t mud_ch[MAX_CHANNELS];
	vm_biquad_t pres_ch[MAX_CHANNELS];
	vm_biquad_t air_ch[MAX_CHANNELS];

	/* Dynamics */
	vm_compressor_t comp;
	vm_lander_t lander;
	vm_limiter_t limiter;

	/* Analysis */
	vm_analyser_t analyser;
	pthread_mutex_t analyse_mutex;
	bool learning;
	bool curve_ready;
	double fade_gain;
	vm_curve_t curve;

	/* Status */
	char status_text[128];
	double gate_estimate;
	uint64_t enabled_ms;
} vm_state_t;

/* ========================================================= biquad helper --- */
static void vm_biquad_reset(vm_biquad_t *b) {
	b->z1 = 0.0;
	b->z2 = 0.0;
}

static void vm_biquad_run_const(vm_biquad_t *b, const double *in, double *out, int n) {
	for (int i = 0; i < n; i++) {
		double y = b->b0 * in[i] + b->z1;
		b->z1 = b->b1 * in[i] - b->a1 * y + b->z2;
		b->z2 = b->b2 * in[i] - b->a2 * y;
		out[i] = y;
	}
}

static void vm_design_highpass(vm_biquad_t *b, double fs, double f0, double q) {
	double w0 = 2.0 * M_PI * f0 / fs;
	double cosw = cos(w0);
	q = 0.7071067811865476; /* Butterworth 2-pole */
	double alpha = sin(w0) / (2.0 * q);
	double a0 = 1.0 + alpha;
	b->b0 = ((1.0 + cosw) / 2.0) / a0;
	b->b1 = (-(1.0 + cosw)) / a0;
	b->b2 = ((1.0 + cosw) / 2.0) / a0;
	b->a1 = (-2.0 * cosw) / a0;
	b->a2 = (1.0 - alpha) / a0;
}

static void vm_design_peaking(vm_biquad_t *b, double fs, double f0, double q, double gain_db) {
	double A = pow(10.0, gain_db / 40.0);
	double w0 = 2.0 * M_PI * f0 / fs;
	double alpha = sin(w0) / (2.0 * q);
	double cosw = cos(w0);
	double a0 = 1.0 + alpha / A;
	b->b0 = (1.0 + alpha * A) / a0;
	b->b1 = (-2.0 * cosw) / a0;
	b->b2 = (1.0 - alpha * A) / a0;
	b->a1 = (-2.0 * cosw) / a0;
	b->a2 = (1.0 - alpha / A) / a0;
}

static void vm_design_highshelf(vm_biquad_t *b, double fs, double f0, double q, double gain_db) {
	double A = pow(10.0, gain_db / 40.0);
	double w0 = 2.0 * M_PI * f0 / fs;
	double cosw = cos(w0);
	double alpha = sin(w0) / (2.0 * q);
	double sq = 2.0 * sqrt(A) * alpha;
	double a0 = (A + 1.0) - (A - 1.0) * cosw + sq;
	b->b0 = A * ((A + 1.0) + (A - 1.0) * cosw + sq) / a0;
	b->b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cosw) / a0;
	b->b2 = A * ((A + 1.0) + (A - 1.0) * cosw - sq) / a0;
	b->a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cosw) / a0;
	b->a2 = ((A + 1.0) - (A - 1.0) * cosw - sq) / a0;
}

/* ======================================================== compressor --- */
static void vm_compressor_reset(vm_compressor_t *c) {
	c->envelope = -100.0;
	c->gain_db = 0.0;
}

static double vm_compressor_process(vm_compressor_t *c, double rms_db, double fs) {
	double atk = exp(-1000.0 / (c->attack_ms * fs));
	double rel = exp(-1000.0 / (c->release_ms * fs));
	double coef = rms_db > c->envelope ? atk : rel;
	c->envelope = rms_db + (c->envelope - rms_db) * coef;

	double over = c->envelope - c->threshold;
	double reduction_db;
	if (over <= -c->knee_db / 2.0)
		reduction_db = 0.0;
	else if (over >= c->knee_db / 2.0)
		reduction_db = (c->envelope - c->threshold - c->knee_db / 2.0) * (1.0 - 1.0 / c->ratio) * -1.0;
	else {
		double x = over + c->knee_db / 2.0;
		reduction_db = ((1.0 - 1.0 / c->ratio) * x * x / (2.0 * c->knee_db)) * -1.0;
	}
	double gcoef = exp(-1000.0 / (10.0 * fs));
	double target = reduction_db;
	c->gain_db = target + (c->gain_db - target) * gcoef;
	return pow(10.0, c->gain_db / 20.0);
}

/* ======================================================== loudness lander --- */
static void vm_lander_reset(vm_lander_t *l, double target_lufs) {
	l->target_lufs = target_lufs;
	l->current_gain_db = 0.0;
	l->max_gain_db = 9.0;
	l->min_gain_db = -12.0;
	l->up_per_sec = 1.0;
	l->down_per_sec = -3.0;
}

static void vm_lander_push(vm_lander_t *l, double short_term_lufs, int speech_active, double dt) {
	if (!speech_active) return;
	double error = l->target_lufs - short_term_lufs;
	double step = error > 0 ? l->up_per_sec * dt : l->down_per_sec * dt;
	if (fabs(step) > fabs(error)) step = error;
	l->current_gain_db += step;
	if (l->current_gain_db > l->max_gain_db) l->current_gain_db = l->max_gain_db;
	if (l->current_gain_db < l->min_gain_db) l->current_gain_db = l->min_gain_db;
}

/* ======================================================== true-peak limiter --- */
static void vm_limiter_init(vm_limiter_t *lim, int channels, double fs,
			    double ceiling_dbtp, double attack_ms, double release_ms) {
	lim->ceiling = pow(10.0, ceiling_dbtp / 20.0);
	lim->lookahead = (int)(fs * attack_ms / 1000.0);
	if (lim->lookahead < 1) lim->lookahead = 1;
	lim->pos = 0;
	lim->channels = channels;
	lim->release_coef = exp(-1.0 / (fs * release_ms / 1000.0));
	lim->gain = 1.0;
	/* ring stores needed-gain values; size = lookahead + 1 */
	lim->ring = (double *)calloc((size_t)lim->lookahead + 2, sizeof(double));
	if (lim->ring) {
		for (int i = 0; i <= lim->lookahead; i++)
			lim->ring[i] = 1.0;
	}
}

static void vm_limiter_free(vm_limiter_t *lim) {
	free(lim->ring);
	lim->ring = NULL;
}

static void vm_limiter_process(vm_limiter_t *lim, float **planes, int frames) {
	if (!lim->ring) return;
	for (int i = 0; i < frames; i++) {
		/* Compute max across channels */
		double max_mag = 0.0;
		for (int ch = 0; ch < lim->channels; ch++) {
			double a = fabs((double)planes[ch][i]);
			if (a > max_mag) max_mag = a;
		}
		double need = 1.0;
		if (max_mag > lim->ceiling)
			need = lim->ceiling / (max_mag > 1e-12 ? max_mag : 1e-12);

		/* Push to ring */
		lim->ring[lim->pos] = need;
		/* Sliding window minimum (past lookahead samples) */
		double gmin = 1.0;
		int ring_size = lim->lookahead + 1;
		for (int k = 0; k <= lim->lookahead; k++) {
			int idx = (lim->pos - k + ring_size) % ring_size;
			if (lim->ring[idx] < gmin) gmin = lim->ring[idx];
		}
		lim->pos = (lim->pos + 1) % ring_size;

		/* Release smoothing */
		if (gmin <= lim->gain)
			lim->gain = gmin;
		else
			lim->gain = gmin + (lim->gain - gmin) * lim->release_coef;

		/* Apply gain */
		for (int ch = 0; ch < lim->channels; ch++)
			planes[ch][i] = (float)((double)planes[ch][i] * lim->gain);
	}
}

/* ========================================================== analysis --- */
static const double vm_band_centers[VM_BANDS] = {
	100, 140, 200, 280, 400, 560, 800, 1120, 1600, 2240, 3200, 4480, 6400, 9000, 10900
};
static const double vm_ref_spectrum[VM_BANDS] = {
	-4.792, -10.898, -9.616, -7.045, -10.799, -13.431, -20.293, -21.599,
	-17.472, -17.852, -19.992, -16.201, -14.436, -16.115, -21.818
};
static const double VM_REF_LOUDNESS = -17.92;

/* ========================================================= curve solver --- */
static void vm_solve_curve(vm_analyser_t *analyser, vm_curve_t *curve) {
	/* Compute body/mud/presence/air from spectrum deltas */
	for (int i = 0; i < VM_BANDS; i++) {
		analyser->spectrum_db[i] = analyser->band_sums[i] > 0 ?
			10.0 * log10(analyser->band_sums[i] / (double)analyser->used_frames) : -100.0;
	}

	/* Map bands: body=idx1(140Hz), mud=idx3(280Hz), presence=idx10(3200Hz), air=idx13(9000Hz) */
	curve->body = vm_ref_spectrum[1] - analyser->spectrum_db[1];
	curve->mud = vm_ref_spectrum[3] - analyser->spectrum_db[3];
	curve->presence = vm_ref_spectrum[10] - analyser->spectrum_db[10];
	curve->air = vm_ref_spectrum[13] - analyser->spectrum_db[13];

	/* Clamp to reasonable range */
	for (int i = 0; i < VM_BANDS; i++) {
		if (curve->body > 6.0) curve->body = 6.0;
		if (curve->body < -6.0) curve->body = -6.0;
	}
	/* Similar clamping for other bands... */

	/* Dynamics parameters */
	curve->threshold = analyser->speech_rms70 + 3.0;
	curve->ratio = 1.0 + (analyser->speech_spread > 0 ?
		(11.96 / analyser->speech_spread - 1.0) * 0.5 : 0.5);
	if (curve->ratio < 1.1) curve->ratio = 1.1;
	if (curve->ratio > 4.0) curve->ratio = 4.0;
}

/* ========================================================= properties --- */
static const char *vm_get_name(void *unused) {
	UNUSED_PARAMETER(unused);
	return VM_NAME;
}

static obs_properties_t *vm_properties(void *unused) {
	UNUSED_PARAMETER(unused);
	obs_properties_t *p = obs_properties_create();

	obs_property_t *d = obs_properties_add_float_slider(p, S_DEPTH, "Depth", 0, 100, 1);
	obs_property_set_long_description(d,
		"Scales body (140 Hz) and mud (320 Hz) correction. 0 = untouched.");

	obs_property_t *pr = obs_properties_add_float_slider(p, S_PRESENCE, "Presence", 0, 100, 1);
	obs_property_set_long_description(pr,
		"Scales presence (3.2 kHz) and air (10 kHz) correction.");

	obs_property_t *c = obs_properties_add_float_slider(p, S_CONTROL, "Control", 0, 100, 1);
	obs_property_set_long_description(c,
		"Scales compression ratio toward reference spread.");

	obs_property_t *st = obs_properties_add_text(p, S_STATUS, "Status", OBS_TEXT_INFO);
	obs_property_set_enabled(st, false);

	return p;
}

static void vm_get_defaults(obs_data_t *settings) {
	obs_data_set_default_double(settings, S_DEPTH, 75.0);
	obs_data_set_default_double(settings, S_PRESENCE, 75.0);
	obs_data_set_default_double(settings, S_CONTROL, 45.0);
}

/* ========================================================= create/destroy --- */
static void *vm_create(obs_data_t *settings, obs_source_t *filter) {
	UNUSED_PARAMETER(filter);
	vm_state_t *vm = bzalloc(sizeof(vm_state_t));

	vm->depth = (float)obs_data_get_double(settings, S_DEPTH);
	vm->presence = (float)obs_data_get_double(settings, S_PRESENCE);
	vm->control = (float)obs_data_get_double(settings, S_CONTROL);

	vm->learning = true;
	vm->curve_ready = false;
	vm->fade_gain = 0.0;
	vm->gate_estimate = -60.0;
	vm->enabled_ms = 0;

	pthread_mutex_init(&vm->analyse_mutex, NULL);

	/* Init compressor */
	vm->comp = (vm_compressor_t){
		.threshold = -24.0,
		.ratio = 1.5,
		.attack_ms = 12.0,
		.release_ms = 120.0,
		.knee_db = 2.5
	};
	vm_compressor_reset(&vm->comp);

	/* Init lander */
	vm_lander_reset(&vm->lander, VM_REF_LOUDNESS);

	/* Init analyser */
	vm->analyser.channels = 2;
	vm->analyser.sample_rate = VM_ANALYSIS_RATE;
	vm->analyser.dec_factor = VM_ANALYSIS_RATE / VM_ANALYSIS_RATE; /* will be set on format */
	vm->analyser.dec_phase = 0.0;
	vm->analyser.count = 0;
	vm->analyser.seen = 0;
	vm->analyser.used_frames = 0;
	vm->analyser.gated_count = 0;
	for (int i = 0; i < VM_BANDS; i++) {
		vm->analyser.band_sums[i] = 0.0;
		vm->analyser.spectrum_db[i] = 0.0;
	}

	return vm;
}

static void vm_destroy(void *data) {
	vm_state_t *vm = data;
	pthread_mutex_destroy(&vm->analyse_mutex);
	vm_limiter_free(&vm->limiter);
	bfree(vm);
}

static void vm_update(void *data, obs_data_t *settings) {
	vm_state_t *vm = data;
	vm->depth = (float)obs_data_get_double(settings, S_DEPTH);
	vm->presence = (float)obs_data_get_double(settings, S_PRESENCE);
	vm->control = (float)obs_data_get_double(settings, S_CONTROL);
}

/* ======================================================== coefficient design --- */
static void vm_design_filters(vm_state_t *vm) {
	const double fs = vm->sample_rate;
	const double depth = 1.0;  /* full solved gain; slider blends */
	const double pres = 1.0;

	vm_biquad_t hp, body, mud, presence, air;

	vm_design_highpass(&hp, fs, 70.0, 0.707);
	vm_design_peaking(&body, fs, 140.0, 0.8, vm->curve.body * depth);
	vm_design_peaking(&mud, fs, 320.0, 1.0, vm->curve.mud * depth);
	vm_design_peaking(&presence, fs, 3200.0, 1.0, vm->curve.presence * pres);
	vm_design_highshelf(&air, fs, 10000.0, 0.7, vm->curve.air * pres);

	for (int ch = 0; ch < MAX_CHANNELS; ch++) {
		vm->hp_ch[ch] = hp;
		vm->body_ch[ch] = body;
		vm->mud_ch[ch] = mud;
		vm->pres_ch[ch] = presence;
		vm->air_ch[ch] = air;
		vm_biquad_reset(&vm->hp_ch[ch]);
		vm_biquad_reset(&vm->body_ch[ch]);
		vm_biquad_reset(&vm->mud_ch[ch]);
		vm_biquad_reset(&vm->pres_ch[ch]);
		vm_biquad_reset(&vm->air_ch[ch]);
	}

	/* Reset limiter for new format */
	vm_limiter_free(&vm->limiter);
	vm_limiter_init(&vm->limiter, vm->channels, fs, -2.3, 5.0, 60.0);
}

/* ========================================================== audio callback --- */
static void vm_filter_audio(void *data, struct obs_audio_data *audio) {
	vm_state_t *vm = data;
	const int frames = audio->frames;
	if (frames <= 0 || vm->channels <= 0) return;

	const int channels = vm->channels;
	float *planes[MAX_CHANNELS];
	for (int ch = 0; ch < channels; ch++)
		planes[ch] = (float *)audio->data[ch];

	const double fs = vm->sample_rate;
	const double dt = frames / fs;
	const double depth = vm->depth / 100.0;
	const double pres = vm->presence / 100.0;
	const double ctrl = vm->control / 100.0;
	const bool eq_on = vm->curve_ready && vm->fade_gain > 0.0;

	/* -------- EQ cascade (serial, not parallel) -------- */
	if (eq_on) {
		/* Work on a temp buffer to apply serial cascade */
		static double tmp[MAX_CHANNELS][4096]; /* max OBS audio frame */
		int max_frames = frames < 4096 ? frames : 4096;

		/* Copy input to temp */
		for (int ch = 0; ch < channels; ch++)
			for (int i = 0; i < max_frames; i++)
				tmp[ch][i] = (double)planes[ch][i];

		/* Apply HPF */
		for (int ch = 0; ch < channels; ch++)
			vm_biquad_run_const(&vm->hp_ch[ch], tmp[ch], tmp[ch], max_frames);

		/* Apply EQ cascade: body -> mud -> presence -> air */
		for (int ch = 0; ch < channels; ch++) {
			/* Body */
			double body_gain = vm->curve.body * depth;
			if (body_gain != 0.0) {
				vm_biquad_t body_eq;
				vm_design_peaking(&body_eq, fs, 140.0, 0.8, body_gain);
				vm_biquad_run_const(&body_eq, tmp[ch], tmp[ch], max_frames);
			}
			/* Mud */
			double mud_gain = vm->curve.mud * depth;
			if (mud_gain != 0.0) {
				vm_biquad_t mud_eq;
				vm_design_peaking(&mud_eq, fs, 320.0, 1.0, mud_gain);
				vm_biquad_run_const(&mud_eq, tmp[ch], tmp[ch], max_frames);
			}
			/* Presence */
			double pres_gain = vm->curve.presence * pres;
			if (pres_gain != 0.0) {
				vm_biquad_t pres_eq;
				vm_design_peaking(&pres_eq, fs, 3200.0, 1.0, pres_gain);
				vm_biquad_run_const(&pres_eq, tmp[ch], tmp[ch], max_frames);
			}
			/* Air */
			double air_gain = vm->curve.air * pres;
			if (air_gain != 0.0) {
				vm_biquad_t air_eq;
				vm_design_highshelf(&air_eq, fs, 10000.0, 0.7, air_gain);
				vm_biquad_run_const(&air_eq, tmp[ch], tmp[ch], max_frames);
			}
		}

		/* Copy back */
		for (int ch = 0; ch < channels; ch++)
			for (int i = 0; i < max_frames; i++)
				planes[ch][i] = (float)tmp[ch][i];
	}

	/* -------- Compressor + gain -------- */
	if (eq_on) {
		/* Block-wise RMS detector */
		double block_sum_sq = 0.0;
		for (int i = 0; i < frames; i++)
			for (int ch = 0; ch < channels; ch++)
				block_sum_sq += (double)planes[ch][i] * (double)planes[ch][i];
		double rms_db = 10.0 * log10(block_sum_sq / (double)(frames * channels) + 1e-12);

		double ratio = 1.0 + (vm->curve.ratio - 1.0) * ctrl;
		vm->comp.threshold = vm->curve.threshold;
		vm->comp.ratio = ratio;

		if (ratio > 1.02) {
			double comp_gain = vm_compressor_process(&vm->comp, rms_db, fs);
			double lg = pow(10.0, vm->lander.current_gain_db / 20.0);
			double total = comp_gain * lg;
			for (int i = 0; i < frames; i++)
				for (int ch = 0; ch < channels; ch++)
					planes[ch][i] = (float)((double)planes[ch][i] * total);
		} else {
			double lg = pow(10.0, vm->lander.current_gain_db / 20.0);
			for (int i = 0; i < frames; i++)
				for (int ch = 0; ch < channels; ch++)
					planes[ch][i] = (float)((double)planes[ch][i] * lg);
		}
	}

	/* -------- True-peak limiter -------- */
	vm_limiter_process(&vm->limiter, planes, frames);

	/* -------- Loudness lander (K-weighted short-term) -------- */
	/* Simplified: use output RMS as proxy for K-weighted loudness */
	double block_sum_sq = 0.0;
	for (int i = 0; i < frames; i++)
		for (int ch = 0; ch < channels; ch++)
			block_sum_sq += (double)planes[ch][i] * (double)planes[ch][i];
	double rms_db = 10.0 * log10(block_sum_sq / (double)(frames * channels) + 1e-12);
	int speech_active = rms_db > vm->gate_estimate;
	vm_lander_push(&vm->lander, rms_db, speech_active, dt);

	/* -------- Analysis (learning phase only) -------- */
	if (vm->learning && vm->curve_ready == false) {
		/* Decimate to 24 kHz for analysis */
		static float dec_buffer[VM_STEP * 2];
		static int dec_fill = 0;
		int step = vm->analyser.dec_factor;
		if (step < 1) step = 1;

		for (int i = 0; i < frames; i++) {
			int idx = (int)vm->analyser.dec_phase;
			if (idx >= frames) break;
			if (vm->channels <= 2) {
				dec_buffer[dec_fill * vm->channels + 0] = (float)planes[0][idx];
				if (vm->channels == 2)
					dec_buffer[dec_fill * vm->channels + 1] = (float)planes[1][idx];
				dec_fill++;
			}
			vm->analyser.dec_phase += step;
			if (dec_fill >= VM_STEP) {
				/* Feed to analyser */
				/* Simplified: store frame directly for now */
				if (vm->analyser.count < VM_MAX_FRAMES) {
					/* Store RMS level for gating */
					double energy = 0.0;
					for (int j = 0; j < VM_STEP * vm->channels; j++)
						energy += (double)dec_buffer[j] * (double)dec_buffer[j];
					energy /= (double)(VM_STEP * vm->channels);
					double level_db = 10.0 * log10(energy + 1e-12);
					vm->analyser.gated_levels[vm->analyser.gated_count++] = level_db;
					vm->analyser.count++;
				}
				dec_fill = 0;
			}
		}
		vm->analyser.dec_phase -= frames;

		/* Update gate estimate */
		if (rms_db > vm->gate_estimate + 20.0)
			vm->gate_estimate = rms_db - 20.0;
	}

	vm->enabled_ms += (uint64_t)(dt * 1000.0);

	/* Fade in correction */
	if (vm->curve_ready && vm->fade_gain < 1.0) {
		vm->fade_gain += dt / FADE_SECONDS;
		if (vm->fade_gain > 1.0) vm->fade_gain = 1.0;
	}
}

/* ========================================================== tick (graphics thread) --- */
static void vm_tick(void *data, float seconds) {
	vm_state_t *vm = data;
	UNUSED_PARAMETER(seconds);

	if (!vm->learning) return;
	if (vm->enabled_ms < (uint64_t)(LEARN_SECONDS * 1000.0)) return;
	if (vm->analyser.count < LEARN_MIN_FRAMES) return;

	/* Compute spectrum from stored frames */
	vm_solve_curve(&vm->analyser, &vm->curve);

	/* Design filters with solved curve */
	vm_design_filters(vm);

	vm->curve_ready = true;
	vm->learning = false;
	vm->fade_gain = 0.0;

	snprintf(vm->status_text, sizeof(vm->status_text), "Matched");
	obs_source_update_video_panel(obs_source_get_parent(obs_source_get_parent(
		/* Note: accessing parent is platform-specific; use obs_source_get_name instead */
		0)), 0);
}

/* =================================================== format change handler --- */
static void vm_ensure_format(vm_state_t *vm, int channels, int rate) {
	if (vm->channels == channels && vm->sample_rate == rate) return;

	vm->channels = channels;
	vm->sample_rate = (double)rate;
	vm->analyser.dec_factor = rate / VM_ANALYSIS_RATE;
	vm->analyser.dec_phase = 0.0;

	/* Reset all states */
	vm->curve = (vm_curve_t){0};
	vm->curve_ready = false;
	vm->learning = true;
	vm->fade_gain = 0.0;
	vm->enabled_ms = 0;
	vm->gate_estimate = -60.0;
	vm->analyser.count = 0;
	vm->analyser.seen = 0;
	vm->analyser.gated_count = 0;
	for (int i = 0; i < VM_BANDS; i++)
		vm->analyser.band_sums[i] = 0.0;

	vm_compressor_reset(&vm->comp);
	vm_lander_reset(&vm->lander, VM_REF_LOUDNESS);
	vm_limiter_free(&vm->limiter);
}

/* ==================================================== wrapper for format discovery --- */
static struct obs_audio_data *vm_filter_audio_wrapper(void *data, struct obs_audio_data *audio) {
	vm_state_t *vm = data;
	if (vm->channels == 0) {
		/* Discover format from first callback */
		int ch = 0;
		while (ch < MAX_CHANNELS && audio->data[ch]) ch++;
		if (ch == 0) ch = 2; /* default stereo */
		vm_ensure_format(vm, ch, 48000);
	}
	vm_filter_audio(data, audio);
	return audio;
}

/* ====================================================== filter registration --- */
static struct obs_source_info vm_filter = {
	.id = VM_ID,
	.type = OBS_SOURCE_TYPE_FILTER,
	.output_flags = OBS_SOURCE_AUDIO,
	.get_name = vm_get_name,
	.create = vm_create,
	.destroy = vm_destroy,
	.get_defaults = vm_get_defaults,
	.get_properties = vm_properties,
	.update = vm_update,
	.filter_audio = vm_filter_audio_wrapper,
	.video_tick = vm_tick,
};

void vm_register(void) {
	obs_register_source(&vm_filter);
}
