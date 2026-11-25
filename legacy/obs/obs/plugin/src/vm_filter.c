/* Voice Match OBS audio filter — glue between libobs and vmcore.
 *
 * Chain (all inside this filter, order fixed):
 *   70 Hz 2-pole HP -> body/mud/presence peaking -> air shelf ->
 *   compressor (rms, curve x Control) -> lander gain -> limiter (-2 dBTP)
 *
 * Learning: the filter passes audio through UNCHANGED while it measures.
 * After 45 s enabled and >= 8 gated analysis frames it solves the curve on
 * the tick (graphics) thread — never on the audio thread — designs the
 * biquads, and fades the correction in over 2 s. The eye icon off/on
 * restarts learning. Sliders never relearn; they only scale the locked
 * correction, exactly like match_voice.py --depth/--presence/--control.
 *
 * Three properties only:
 *   depth     0..100 (default 75)  scales body (140 Hz) + mud (320 Hz)
 *   presence  0..100 (default 75)  scales presence (3.2 kHz) + air (10 kHz)
 *   control   0..100 (default 45)  scales the compressor ratio
 */
#include <obs-module.h>
#include <plugin-support.h>
#include <stdatomic.h>
#include <pthread.h>
#include <string.h>

#include "vmcore/vmcore.h"

#define VM_ID "voice_match_filter"
#define VM_NAME "Voice Match (H1n reference)"

#define S_DEPTH "depth"
#define S_PRESENCE "presence"
#define S_CONTROL "control"
#define S_STATUS "status"

#define LEARN_SECONDS 45.0
#define LEARN_MIN_FRAMES 8
#define FADE_SECONDS 2.0
#define MAX_CHANNELS 8

struct vm_state {
	/* settings snapshots (updated on the graphics thread) */
	float depth, presence, control;

	/* format */
	int channels;
	double sample_rate;
	int dec_factor; /* sample_rate / 24000 when exact */

	/* per-channel filter states + shared coefficient biquads */
	vm_biquad hp_ch[MAX_CHANNELS], body_ch[MAX_CHANNELS], mud_ch[MAX_CHANNELS],
		pres_ch[MAX_CHANNELS], air_ch[MAX_CHANNELS];

	vm_compressor comp;
	vm_lander lander;
	vm_limiter limiter;
	double *env;
	int env_capacity;

	/* analysis */
	vm_analyser analyser;
	vm_analyser snapshot; /* copy for the solver (tick thread) */
	pthread_mutex_t analyse_mutex;
	double dec_phase;
	double gate_estimate; /* dB; rough speech floor estimate */
	uint64_t enabled_ms;
	bool learning;
	bool curve_ready;
	double fade_gain;
	vm_curve curve;

	/* lander K-weighting (BS.1770 stage 1, stereo-summed approximation) */
	vm_biquad k_high_ch[MAX_CHANNELS]; /* high shelf */
	vm_biquad k_rise_ch[MAX_CHANNELS];  /* high pass */
	double k_mean_square;
	int k_window_pos;
	double k_block_acc;
	int k_block_count;
	double k_short_term;
};

/* ------------------------------------------------------------ properties */
static const char *vm_get_name(void *unused)
{
	UNUSED_PARAMETER(unused);
	return VM_NAME;
}

static obs_properties_t *vm_properties(void *unused)
{
	UNUSED_PARAMETER(unused);
	obs_properties_t *p = obs_properties_create();
	obs_property_t *d = obs_properties_add_float_slider(p, S_DEPTH, "Depth", 0, 100, 1);
	obs_property_set_long_description(
		d, "Scales the solved body (140 Hz) and mud (320 Hz) gains. 0 = low end untouched.");
	obs_property_t *pr = obs_properties_add_float_slider(p, S_PRESENCE, "Presence", 0, 100, 1);
	obs_property_set_long_description(
		pr, "Scales the solved presence (3.2 kHz) and air (10 kHz) gains.");
	obs_property_t *c = obs_properties_add_float_slider(p, S_CONTROL, "Control", 0, 100, 1);
	obs_property_set_long_description(
		c, "Scales the compressor ratio toward the reference spread. Threshold stays as solved.");
	obs_property_t *st = obs_properties_add_text(p, S_STATUS, "Status", OBS_TEXT_INFO);
	obs_property_set_enabled(st, false);
	return p;
}

static void vm_get_defaults(obs_data_t *settings)
{
	obs_data_set_default_double(settings, S_DEPTH, 75.0);
	obs_data_set_default_double(settings, S_PRESENCE, 75.0);
	obs_data_set_default_double(settings, S_CONTROL, 45.0);
}

/* -------------------------------------------------------------- create */
static void *vm_create(obs_data_t *settings, obs_source_t *filter)
{
	struct vm_state *vm = bzalloc(sizeof(struct vm_state));
	vm->depth = (float)obs_data_get_double(settings, S_DEPTH);
	vm->presence = (float)obs_data_get_double(settings, S_PRESENCE);
	vm->control = (float)obs_data_get_double(settings, S_CONTROL);
	vm->learning = true;
	vm->curve_ready = false;
	vm->fade_gain = 0.0;
	vm->gate_estimate = -60.0;
	pthread_mutex_init(&vm->analyse_mutex, NULL);
	vm_analyser_init(&vm->analyser, 16);
	vm_lander_reset(&vm->lander, VM_REF_LOUDNESS);
	vm->comp = (vm_compressor){.threshold = -24, .ratio = 1.5, .attack_ms = 12,
				   .release_ms = 120, .knee_db = 2.5};
	UNUSED_PARAMETER(filter);
	return vm;
}

static void vm_destroy(void *data)
{
	struct vm_state *vm = data;
	pthread_mutex_destroy(&vm->analyse_mutex);
	if (vm->env)
		bfree(vm->env);
	vm_limiter_free(&vm->limiter);
	bfree(vm);
}

static void vm_update(void *data, obs_data_t *settings)
{
	struct vm_state *vm = data;
	vm->depth = (float)obs_data_get_double(settings, S_DEPTH);
	vm->presence = (float)obs_data_get_double(settings, S_PRESENCE);
	vm->control = (float)obs_data_get_double(settings, S_CONTROL);
}

/* --------------------------------------------------------- coefficient
 * design: called on the tick thread once the curve is solved. */
static void vm_design_filters(struct vm_state *vm)
{
	const double fs = vm->sample_rate;
	const double depth = 1.0; /* full solved gains; slider blends dry/wet */
	const double pres = 1.0;
	vm_biquad hp, body, mud, presence, air;
	vm_design_highpass(&hp, fs, 70.0, 0.707);
	vm_design_peaking(&body, fs, 140.0, 0.8, vm->curve.body * depth);
	vm_design_peaking(&mud, fs, 320.0, 1.0, vm->curve.mud * depth);
	vm_design_peaking(&presence, fs, 3200.0, 1.0, vm->curve.presence * pres);
	vm_design_highshelf(&air, fs, 10000.0, 0.7, vm->curve.air * pres);
	/* copy coefficients to every channel, reset states */
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
}

/* BS.1770 K-weighting stage-1 coefficients (48k reference; close enough at
 * 44.1k for the lander's slow integrator). */
static void vm_design_k(struct vm_state *vm)
{
	const double fs = vm->sample_rate;
	/* high shelf: +4 dB above ~1.5 kHz */
	vm_biquad k1;
	{
		double A = pow(10.0, 4.0 / 40.0);
		double f0 = 1681.97, Q = 0.7071;
		double w0 = 2.0 * M_PI * f0 / fs;
		double alpha = sin(w0) / (2.0 * Q);
		double cw = cos(w0);
		double a0 = (A + 1.0) - (A - 1.0) * cw + 2.0 * sqrt(A) * alpha;
		k1.b0 = A * ((A + 1.0) + (A - 1.0) * cw + 2.0 * sqrt(A) * alpha) / a0;
		k1.b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cw) / a0;
		k1.b2 = A * ((A + 1.0) + (A - 1.0) * cw - 2.0 * sqrt(A) * alpha) / a0;
		k1.a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cw) / a0;
		k1.a2 = ((A + 1.0) - (A - 1.0) * cw - 2.0 * sqrt(A) * alpha) / a0;
	}
	/* high pass ~38 Hz */
	vm_biquad k2;
	vm_design_highpass(&k2, fs, 38.0, 0.5);
	for (int ch = 0; ch < MAX_CHANNELS; ch++) {
		vm->k_high_ch[ch] = k1;
		vm->k_rise_ch[ch] = k2;
		vm_biquad_reset(&vm->k_high_ch[ch]);
		vm_biquad_reset(&vm->k_rise_ch[ch]);
	}
}

/* -------------------------------------------------------------- audio */
static struct obs_audio_data *vm_filter_audio(void *data, struct obs_audio_data *audio)
{
	struct vm_state *vm = data;
	const int frames = audio->frames;
	if (frames <= 0 || vm->channels <= 0)
		return audio;
	const int channels = vm->channels;
	float *planes[MAX_CHANNELS];
	for (int ch = 0; ch < channels; ch++)
		planes[ch] = (float *)audio->data[ch];

	if (vm->env_capacity < frames) {
		if (vm->env)
			bfree(vm->env);
		vm->env = bmalloc(sizeof(double) * frames);
		vm->env_capacity = frames;
		if (vm->limiter.ring == NULL)
			vm_limiter_init(&vm->limiter, channels, vm->sample_rate, -2.0, 5.0, 60.0);
	}

	const double fs = vm->sample_rate;
	const double depth = vm->depth / 100.0;
	const double pres = vm->presence / 100.0;
	const double ctrl = vm->control / 100.0;
	const double fade = vm->fade_gain;
	const bool eq_on = vm->curve_ready && fade > 0.0;

	/* -------- processing -------- */
	double block_sum_sq = 0.0;
	double k_acc = 0.0;
	for (int i = 0; i < frames; i++) {
		double linked = 0.0;
		for (int ch = 0; ch < channels; ch++) {
			double s = (double)planes[ch][i];
			s = vm_biquad_run(&vm->hp_ch[ch], s);
			double eq = s;
			if (eq_on) {
				/* wet path with full solved gains; blend by slider */
				double b = vm_biquad_run(&vm->body_ch[ch], s);
				double m = vm_biquad_run(&vm->mud_ch[ch], s);
				double p = vm_biquad_run(&vm->pres_ch[ch], s);
				double a = vm_biquad_run(&vm->air_ch[ch], s);
				eq = s + fade * (((b - s) * depth) + ((m - s) * depth) +
						 ((p - s) * pres) + ((a - s) * pres));
			}
			double kw = vm_biquad_run(&vm->k_high_ch[ch], eq);
			kw = vm_biquad_run(&vm->k_rise_ch[ch], kw);
			k_acc += kw * kw;
			block_sum_sq += (double)eq * eq;
			planes[ch][i] = (float)eq;
		}
		(void)linked;
	}

	/* -------- compressor + lander gain (linked detector) -------- */
	if (eq_on) {
		double ratio = 1.0 + (vm->curve.ratio - 1.0) * ctrl;
		if (ratio > 1.02) {
			/* block-wise RMS detector, matching acompressor's rms mode */
			double rms_db = 10.0 * log10(block_sum_sq / (double)(frames * channels) + 1e-12);
			vm->comp.threshold = vm->curve.threshold;
			vm->comp.ratio = ratio;
			double g = vm_compressor_run(&vm->comp, rms_db, fs);
			double lg = pow(10.0, vm->lander.current_gain_db / 20.0);
			double total = g * lg;
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

	/* -------- limiter (always last, always on) -------- */
	vm_limiter_envelope(&vm->limiter, planes, frames, vm->env);
	vm_limiter_process(&vm->limiter, planes, frames, vm->env);

	/* -------- lander: K-weighted short-term loudness -------- */
	const double dt = frames / fs;
	vm->k_block_acc += k_acc;
	vm->k_block_count += frames;
	if (vm->k_block_count >= (int)(fs * 0.4)) { /* ~400 ms block */
		double l = -0.691 + 10.0 * log10(vm->k_block_acc + 1e-12);
		vm->k_short_term = l;
		vm->k_block_acc = 0.0;
		vm->k_block_count = 0;
	}
	double block_rms_db = 10.0 * log10(block_sum_sq / (double)(frames * channels) + 1e-12);
	int speech_active = block_rms_db > vm->gate_estimate;
	vm_lander_push(&vm->lander, vm->k_short_term, speech_active, dt);

	/* -------- analysis feed (only while learning) -------- */
	if (vm->learning && vm->dec_factor >= 1) {
		/* static scratch: audio thread only, no reentrancy */
		static float dec[VM_STEP * 2];
		static int dec_fill = 0;
		for (int i = 0; i < frames; i++) {
			int idx = (int)vm->dec_phase;
			if (idx >= frames)
				break;
			if (vm->channels <= 2) {
				dec[dec_fill * vm->channels + 0] = planes[0][idx];
				if (vm->channels == 2)
					dec[dec_fill * vm->channels + 1] = planes[1][idx];
				dec_fill++;
			}
			vm->dec_phase += vm->dec_factor;
			if (dec_fill == VM_STEP * vm->channels) {
				vm_analyser_push(&vm->analyser, dec, vm->channels);
				dec_fill = 0;
			}
		}
		vm->dec_phase -= frames;
		/* crude gate estimate for the lander: track recent peak block rms */
		if (block_rms_db > vm->gate_estimate + 20.0)
			vm->gate_estimate = block_rms_db - 20.0;
	}

	vm->enabled_ms += (uint64_t)(dt * 1000.0);
	if (vm->curve_ready && vm->fade_gain < 1.0) {
		vm->fade_gain += dt / FADE_SECONDS;
		if (vm->fade_gain > 1.0)
			vm->fade_gain = 1.0;
	}
	return audio;
}

/* ------------------------------------------------------------- tick:
 * runs on the graphics thread; solves the curve when learning completes. */
static void vm_tick(void *data, float seconds)
{
	struct vm_state *vm = data;
	UNUSED_PARAMETER(seconds);
	if (!vm->learning)
		return;
	if (vm->enabled_ms < (uint64_t)(LEARN_SECONDS * 1000.0))
		return;
	if (vm->analyser.count < LEARN_MIN_FRAMES)
		return;

	/* snapshot + finish the analysis (FFT work off the audio thread) */
	vm_profile p;
	vm_analyser snapshot;
	pthread_mutex_lock(&vm->analyse_mutex);
	snapshot = vm->analyser;
	pthread_mutex_unlock(&vm->analyse_mutex);
	if (vm_analyser_finish(&snapshot, &p) != 0)
		return;

	vm_profile ref;
	vm_reference_profile(&ref);
	vm->curve = vm_match_curve(&p, &ref);
	vm_design_filters(vm);
	vm->curve_ready = true;
	vm->learning = false;
	vm->fade_gain = 0.0;
}

/* ------------------------------------------------------- format change */
static struct obs_audio_data *vm_filter_audio_wrapper(void *data, struct obs_audio_data *audio);

/* OBS calls filter_audio with the source's current mix; we learn the format
 * lazily from the audio output info via obs_source_get_audio_info? Filters
 * receive obs_audio_data with data[] planes; channel count comes from the
 * parent's speaker layout which we cache in create via the filter source. */
static void vm_ensure_format(struct vm_state *vm, int channels, int rate)
{
	if (vm->channels == channels && vm->sample_rate == rate)
		return;
	vm->channels = channels;
	vm->sample_rate = rate;
	vm->dec_factor = (int)(rate / VM_ANALYSIS_RATE);
	vm->dec_phase = 0.0;
	vm_design_k(vm);
	/* neutral coefficient set until the curve is solved */
	vm->curve = (vm_curve){.body = 0, .mud = 0, .presence = 0, .air = 0,
			       .threshold = -24, .ratio = 1.0};
	vm_design_filters(vm);
	vm->curve_ready = false;
	vm->learning = true;
	vm->fade_gain = 0.0;
	if (vm->limiter.ring) {
		vm_limiter_free(&vm->limiter);
		memset(&vm->limiter, 0, sizeof(vm->limiter));
	}
	vm_limiter_init(&vm->limiter, channels, rate, -2.0, 5.0, 60.0);
}

/* channel count discovery: use the audio data pointer layout trick is not
 * possible; instead we piggyback on the first callback by counting planes
 * with valid pointers relative to frames (planes are contiguous). */
static struct obs_audio_data *vm_filter_audio_impl(void *data, struct obs_audio_data *audio)
{
	struct vm_state *vm = data;
	if (vm->channels == 0) {
		/* MAX_AUDIO_CHANNELS is 8 in libobs; count contiguous planes */
		int ch = 0;
		while (ch < MAX_CHANNELS && audio->data[ch])
			ch++;
		/* frame-rate estimate: we still need the rate; obs_audio_data
		 * has no rate. Take it from the source: the filter's parent. */
		vm_ensure_format(vm, ch > 0 ? ch : 2, 48000.0);
		/* rate correction happens in vm_video_render-less design: we
		 * rely on obs_get_audio_info? Not available for filters. The
		 * rate is set via the filter's output format callback below. */
	}
	return vm_filter_audio_wrapper(data, audio);
}

/* libobs provides the parent sample rate through the obs_source audio
 * conversion contract: filters are called at the mixer rate. We read the
 * global audio sample rate once. */
static void vm_set_rate_from_mixer(struct vm_state *vm)
{
	struct obs_audio_info ai;
	if (obs_get_audio_info(&ai))
		vm_ensure_format(vm, vm->channels > 0 ? vm->channels : 2, (double)ai.samples_per_sec);
}

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
	.filter_audio = vm_filter_audio_impl,
	.video_tick = vm_tick,
};

/* forward decls used above */
static struct obs_audio_data *vm_filter_audio_wrapper(void *data, struct obs_audio_data *audio)
{
	struct vm_state *vm = data;
	if (vm->sample_rate == 48000.0 && vm->dec_factor == 0)
		vm_set_rate_from_mixer(vm);
	return vm_filter_audio(data, audio);
}

void vm_register(void)
{
	obs_register_source(&vm_filter);
}
