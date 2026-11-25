/* vmcore profile.h — the compiled-in Zoom H1n reference (schema 1, measured
 * 2026-11 from 211018-075300.WAV by matcher/match_voice.py). Loading the JSON
 * at runtime is optional; these constants are the fallback and the parity
 * test target.
 */
#ifndef VMCORE_PROFILE_H
#define VMCORE_PROFILE_H

#include "analyser.h"

static const double VM_REF_SPECTRUM_DB[VM_BANDS] = {
	-4.792, -10.898, -9.616, -7.045, -10.799, -13.431, -20.293, -21.599,
	-17.472, -17.852, -19.992, -16.201, -14.436, -16.115, -21.818};
static const double VM_REF_LOUDNESS = -17.92;
static const double VM_REF_TRUE_PEAK = -1.86;
static const double VM_REF_LRA = 8.8;
static const double VM_REF_SPEECH_RMS70 = -17.4;
static const double VM_REF_SPEECH_SPREAD = 11.96;
static const int VM_REF_SAMPLE_RATE = 48000;

static void vm_reference_profile(vm_profile *p)
{
	for (int i = 0; i < VM_BANDS; i++)
		p->spectrum_db[i] = VM_REF_SPECTRUM_DB[i];
	p->loudness = VM_REF_LOUDNESS;
	p->true_peak = VM_REF_TRUE_PEAK;
	p->speech_rms70 = VM_REF_SPEECH_RMS70;
	p->speech_spread = VM_REF_SPEECH_SPREAD;
	p->sample_rate = VM_REF_SAMPLE_RATE;
	p->channels = 2;
}

#endif
