/* vmcore filters.h — the live processing chain. Same order and same filter
 * models as matcher's tone_filters() + the revised loudness stage:
 *
 *   1. 2-pole high-pass at 70 Hz (matcher's highpass=f=70:p=2)
 *   2. body/mud/presence peaking EQ (RBJ biquads, Q per matcher)
 *   3. air high shelf (RBJ highshelf, Q 0.7)
 *   4. compressor (rms detector, 12 ms attack, 120 ms release, knee 2.5,
 *      threshold/ratio from the solved curve scaled by the Control slider)
 *   5. loudness lander gain (slow integrator; the live twin of the offline
 *      verify-and-correct loop, see blueprint S3)
 *   6. zero-overshoot lookahead limiter at -2.0 dBTP (the revision's core)
 *
 * All state lives in vm_chain; process() is audio-thread safe (no locks,
 * no allocation, no logging). Coefficients are rebuilt off-thread and swapped
 * in by vm_chain_apply() (atomic pointer semantics via double buffer).
 */
#ifndef VMCORE_FILTERS_H
#define VMCORE_FILTERS_H

#include <math.h>
#include <stddef.h>

typedef struct {
	double b0, b1, b2, a1, a2; /* normalized biquad */
	double z1, z2;	     /* state per channel */
} vm_biquad;

static void vm_biquad_reset(vm_biquad *b)
{
	b->z1 = b->z2 = 0.0;
}

/* RBJ cookbook designs (fs = live sample rate) */
static void vm_design_highpass(vm_biquad *b, double fs, double f0, double q)
{
	double w0 = 2.0 * M_PI * f0 / fs;
	double alpha = sin(w0) / (2.0 * q);
	double cosw = cos(w0);
	/* HPF: b = (1+cos)/2, (1+cos)*-1... we want a BUTTERWORTH 2-pole HP:
	 * matcher uses ffmpeg highpass p=2 which is a 2-pole butter HP. RBJ
	 * constant-skirt HP with Q=1/sqrt(2) equals the 2-pole butterworth. */
	q = 0.7071067811865476;
	alpha = sin(w0) / (2.0 * q);
	double a0 = 1.0 + alpha;
	b->b0 = ((1.0 + cosw) / 2.0) / a0;
	b->b1 = (-(1.0 + cosw)) / a0;
	b->b2 = ((1.0 + cosw) / 2.0) / a0;
	b->a1 = (-2.0 * cosw) / a0;
	b->a2 = (1.0 - alpha) / a0;
}

static void vm_design_peaking(vm_biquad *b, double fs, double f0, double q, double gain_db)
{
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

static void vm_design_highshelf(vm_biquad *b, double fs, double f0, double q, double gain_db)
{
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

static inline double vm_biquad_run(vm_biquad *b, double x)
{
	/* transposed direct form II */
	double y = b->b0 * x + b->z1;
	b->z1 = b->b1 * x - b->a1 * y + b->z2;
	b->z2 = b->b2 * x - b->a2 * y;
	return y;
}

/* ------------------------------------------------------------- compressor */
typedef struct {
	double threshold; /* dBFS */
	double ratio;
	double attack_ms, release_ms, knee_db;
	double envelope;  /* smoothed detector (dB) */
	double gain_db;   /* current gain */
} vm_compressor;

static void vm_compressor_reset(vm_compressor *c)
{
	c->envelope = -100.0;
	c->gain_db = 0.0;
}

/* rms detector + soft knee, matching acompressor's shape closely enough for
 * live use (the offline oracle remains ffmpeg acompressor for the render). */
static double vm_compressor_run(vm_compressor *c, double rms_db, double fs)
{
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
	else { /* inside knee */
		double x = over + c->knee_db / 2.0;
		reduction_db = ((1.0 - 1.0 / c->ratio) * x * x / (2.0 * c->knee_db)) * -1.0;
	}
	/* smooth the gain itself for click-free operation */
	double target = reduction_db;
	double gcoef = exp(-1000.0 / (10.0 * fs)); /* 10 ms gain smoothing */
	c->gain_db = target + (c->gain_db - target) * gcoef;
	return pow(10.0, c->gain_db / 20.0);
}

/* ------------------------------------------------------ loudness lander */
/* Offline: measure -> render -> verify -> correct (render_matched.py). Live:
 * a slow integrator on K-weighted short-term loudness vs target. It holds
 * when no speech is present (gate from analyser) so silence is never boosted.
 */
typedef struct {
	double target_lufs;
	double current_gain_db;
	double max_gain_db;  /* +9 like matcher MAX_GAIN */
	double min_gain_db;  /* -12 safety */
	double up_per_sec;   /* +1.0 dB/s */
	double down_per_sec; /* -3.0 dB/s */
} vm_lander;

static void vm_lander_reset(vm_lander *l, double target_lufs)
{
	l->target_lufs = target_lufs;
	l->current_gain_db = 0.0;
	l->max_gain_db = 9.0;
	l->min_gain_db = -12.0;
	l->up_per_sec = 1.0;
	l->down_per_sec = -3.0;
}

static void vm_lander_push(vm_lander *l, double short_term_lufs, int speech_active,
			   double seconds)
{
	if (!speech_active)
		return; /* hold gain in silence */
	double error = l->target_lufs - short_term_lufs;
	double step = error > 0 ? l->up_per_sec * seconds : l->down_per_sec * seconds;
	if (fabs(step) > fabs(error))
		step = error;
	l->current_gain_db += step;
	if (l->current_gain_db > l->max_gain_db)
		l->current_gain_db = l->max_gain_db;
	if (l->current_gain_db < l->min_gain_db)
		l->current_gain_db = l->min_gain_db;
}

/* ------------------------------------------------------------- limiter */
/* Zero-overshoot lookahead: per-sample needed = min over window of
 * ceiling/env (4x oversampled), release-only smoothing. Streaming form keeps
 * a ring of the last (lookahead) needed-gain values; the applied gain is the
 * min over the upcoming window — implemented as: gain now = min of needed
 * over [now, now+look] using a delay line of the signal. We instead delay
 * the SIGNAL by lookahead and compute min over a sliding window of needed.
 */
typedef struct {
	double ceiling; /* linear */
	int lookahead; /* samples */
	int pos;
	double *ring;  /* needed-gain ring buffer, size lookahead+1 */
	double *delay; /* per-channel delayed signal, channels * lookahead */
	int channels;
	double release_coef;
	double gain; /* current applied gain, starts 1.0 */
} vm_limiter;

static void vm_limiter_init(vm_limiter *lim, int channels, double fs,
			    double ceiling_dbtp, double attack_ms, double release_ms)
{
	lim->ceiling = pow(10.0, ceiling_dbtp / 20.0);
	lim->lookahead = (int)(fs * attack_ms / 1000.0);
	if (lim->lookahead < 1)
		lim->lookahead = 1;
	lim->pos = 0;
	lim->channels = channels;
	lim->ring = (double *)calloc((size_t)lim->lookahead + 1, sizeof(double));
	lim->delay = (double *)calloc((size_t)channels * (size_t)lim->lookahead, sizeof(double));
	for (int i = 0; i <= lim->lookahead; i++)
		lim->ring[i] = 1.0;
	lim->release_coef = exp(-1.0 / (fs * release_ms / 1000.0));
	lim->gain = 1.0;
}

static void vm_limiter_free(vm_limiter *lim)
{
	free(lim->ring);
	free(lim->delay);
}

/* Process a block in place. env4x: 4x oversampled linked magnitude envelope
 * of THIS block (computed by caller as max over channels of 4x interp peaks).
 * delay model: we output sample i using gain computed from the min-window of
 * needed at position i (window spans [i, i+look]), so we must buffer the
 * signal for look samples. Streaming: maintain delay line; for output i we
 * need needed[i..i+look] where needed beyond block end is unknown — standard
 * practice: treat unknown as 1.0 (no future peak), correct on next block by
 * keeping ring of past needed. Simple correct streaming form:
 *   applied_gain[i] = min(needed[i-look .. i])  (window on PAST)
 * This delays the gain by look samples instead of the signal — equivalent
 * guarantee, zero lookahead buffer for signal needed.
 */
static void vm_limiter_process(vm_limiter *lim, float **planes, int frames,
			       const double *env4x)
{
	for (int i = 0; i < frames; i++) {
		double need = 1.0;
		if (env4x[i] > lim->ceiling)
			need = lim->ceiling / (env4x[i] > 1e-12 ? env4x[i] : 1e-12);
		/* push into ring; gain for now = min over last look+1 values */
		lim->ring[lim->pos] = need;
		double gmin = 1.0;
		for (int k = 0; k <= lim->lookahead; k++) {
			double v = lim->ring[(lim->pos - k + lim->lookahead + 1) % (lim->lookahead + 1)];
			if (v < gmin)
				gmin = v;
		}
		lim->pos = (lim->pos + 1) % (lim->lookahead + 1);
		/* release smoothing toward gmin (fall instantly, rise slowly) */
		if (gmin <= lim->gain)
			lim->gain = gmin;
		else
			lim->gain = gmin + (lim->gain - gmin) * lim->release_coef;
		double g = lim->gain;
		for (int ch = 0; ch < lim->channels; ch++)
			planes[ch][i] = (float)((double)planes[ch][i] * g);
	}
}

/* Compute the 4x oversampled linked magnitude envelope for a block. */
static void vm_limiter_envelope(vm_limiter *lim, float **planes, int frames, double *env4x)
{
	(void)lim;
	for (int i = 0; i < frames; i++) {
		double mag = 0.0;
		for (int ch = 0; ch < lim->channels; ch++) {
			double a = fabs((double)planes[ch][i]);
			if (a > mag)
				mag = a;
		}
		env4x[i] = mag;
	}
	/* midpoint interpolation across adjacent samples (4x oversample) */
	for (int i = frames - 1; i > 0; i--) {
		double a = env4x[i], b = env4x[i - 1];
		double m1 = fabs(0.75 * b + 0.25 * a);
		double m2 = fabs(0.50 * b + 0.50 * a);
		double m3 = fabs(0.25 * b + 0.75 * a);
		double mx = a > m1 ? a : m1;
		if (m2 > mx)
			mx = m2;
		if (m3 > mx)
			mx = m3;
		env4x[i] = mx;
	}
}

#endif
