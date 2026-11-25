/* vmcore/profile.h — Zoom H1n voice reference profile.
 *
 * This is the ground truth for voice matching. Derived from
 * 211018-075300(1).WAV (Zoom H1n, 48 kHz stereo, 132.316 s).
 *
 * SHA-256: 62301ba7068fb83ca90424eed8ba3f14e2be97f9c79c89f551334ace553eab68
 */
#ifndef VMCORE_PROFILE_H
#define VMCORE_PROFILE_H

#include <stdint.h>
#include <string.h>

#define VM_BANDS 15

typedef struct {
	double spectrum_db[VM_BANDS];
	double loudness;
	double true_peak;
	double lra;
	double speech_rms70;
	double speech_spread;
	int sample_rate;
	int channels;
} vm_profile_t;

/* Load the compiled-in reference profile. */
void vm_reference_profile(vm_profile_t *p);

/* Load a user profile from JSON (optional — falls back to compiled-in). */
int vm_load_profile(const char *path, vm_profile_t *p);

#endif /* VMCORE_PROFILE_H */
