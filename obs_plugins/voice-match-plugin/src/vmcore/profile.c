/* vmcore/profile.c — reference profile implementation.
 *
 * Schema 1: 48 kHz stereo, Zoom H1n voice reference.
 * SHA-256: 62301ba7068fb83ca90424eed8ba3f14e2be97f9c79c89f551334ace553eab68
 *
 * Targets:
 *   -17.92 LUFS integrated loudness
 *   -1.86 dBTP true peak (measured)
 *   8.8 LU LRA
 *   11.96 dB speech spread (P90-P20)
 */
#include "profile.h"
#include <string.h>

static const double VM_REF_SPECTRUM_DB[VM_BANDS] = {
	-4.792, -10.898, -9.616, -7.045, -10.799, -13.431, -20.293, -21.599,
	-17.472, -17.852, -19.992, -16.201, -14.436, -16.115, -21.818
};

static const double VM_REF_LOUDNESS = -17.92;
static const double VM_REF_TRUE_PEAK = -1.86;
static const double VM_REF_LRA = 8.8;
static const double VM_REF_SPEECH_RMS70 = -17.4;
static const double VM_REF_SPEECH_SPREAD = 11.96;
static const int VM_REF_SAMPLE_RATE = 48000;

void vm_reference_profile(vm_profile_t *p)
{
	memset(p, 0, sizeof(*p));
	for (int i = 0; i < VM_BANDS; i++)
		p->spectrum_db[i] = VM_REF_SPECTRUM_DB[i];
	p->loudness = VM_REF_LOUDNESS;
	p->true_peak = VM_REF_TRUE_PEAK;
	p->lra = VM_REF_LRA;
	p->speech_rms70 = VM_REF_SPEECH_RMS70;
	p->speech_spread = VM_REF_SPEECH_SPREAD;
	p->sample_rate = VM_REF_SAMPLE_RATE;
	p->channels = 2;
}
