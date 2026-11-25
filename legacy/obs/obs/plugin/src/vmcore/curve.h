/* vmcore curve.h — exact port of matcher's match_curve(): anchor on
 * 500-1750 Hz used bands, targets clamped +/-12, bounded ridge fit over the
 * four filters (body 140 Q0.8, mud 320 Q1.0, presence 3200 Q1.0, air 10000
 * highshelf), 20 passes, caps 4.5/4.5/4.5/2.5, positive-sum budget 4.98,
 * plus compressor threshold/ratio from speechRms70/speechSpread.
 */
#ifndef VMCORE_CURVE_H
#define VMCORE_CURVE_H

#include "analyser.h"
#include <string.h>

typedef struct {
	double body;
	double mud;
	double presence;
	double air;
	double threshold; /* dBFS */
	double ratio;     /* 1.0 .. 3.0 */
} vm_curve;

static double vm_response(double frequency, int is_air, double center, double q)
{
	double relative = frequency / center;
	if (is_air)
		return pow(relative, 4.0) / (1.0 + pow(relative, 4.0));
	double t = relative - 1.0 / relative;
	return 1.0 / (1.0 + q * q * t * t);
}

static double vm_limit(double v, double lo, double hi)
{
	return v < lo ? lo : (v > hi ? hi : v);
}

/* reference: the Zoom H1n profile (or any matcher profile). source: measured.
 * Returns the curve. Mirrors match_curve() line by line.
 */
static vm_curve vm_match_curve(const vm_profile *source, const vm_profile *reference)
{
	static const double centers[4] = {140, 320, 3200, 10000};
	static const double qs[4] = {0.8, 1.0, 1.0, 0.7};
	static const double caps[4] = {4.5, 4.5, 4.5, 2.5};
	static const int is_air[4] = {0, 0, 0, 1};

	double comparable = (double)(source->sample_rate < reference->sample_rate
					   ? source->sample_rate
					   : reference->sample_rate) *
			    0.45;
	double src[VM_BANDS], ref[VM_BANDS];
	memcpy(src, source->spectrum_db, sizeof(src));
	memcpy(ref, reference->spectrum_db, sizeof(ref));
	double src_max = src[0], ref_max = ref[0];
	for (int i = 1; i < VM_BANDS; i++) {
		if (src[i] > src_max)
			src_max = src[i];
		if (ref[i] > ref_max)
			ref_max = ref[i];
	}
	int valid[VM_BANDS], nvalid = 0;
	for (int i = 0; i < VM_BANDS; i++) {
		if (vm_bands_hz[i] < comparable && src[i] >= src_max - 48.0 &&
		    ref[i] >= ref_max - 48.0)
			valid[nvalid++] = i;
	}
	int middle[VM_BANDS], nmid = 0;
	for (int k = 0; k < nvalid; k++) {
		double hz = vm_bands_hz[valid[k]];
		if (hz >= 500.0 && hz <= 1750.0)
			middle[nmid++] = valid[k];
	}
	double gains[4] = {0, 0, 0, 0};
	if (nvalid >= 4 && (nmid > 0 || nvalid > 0)) {
		int *anchor_set = nmid > 0 ? middle : valid;
		int anchor_n = nmid > 0 ? nmid : nvalid;
		double anchor = 0.0;
		for (int k = 0; k < anchor_n; k++)
			anchor += ref[anchor_set[k]] - src[anchor_set[k]];
		anchor /= (double)anchor_n;

		double targets[VM_BANDS];
		for (int k = 0; k < nvalid; k++) {
			double d = ref[valid[k]] - src[valid[k]] - anchor;
			targets[k] = vm_limit(d, -12.0, 12.0);
		}
		double rows[VM_BANDS][4];
		for (int k = 0; k < nvalid; k++)
			for (int j = 0; j < 4; j++)
				rows[k][j] = vm_response(vm_bands_hz[valid[k]], is_air[j],
							 centers[j], qs[j]);
		for (int pass = 0; pass < 20; pass++) {
			for (int j = 0; j < 4; j++) {
				if (centers[j] >= comparable)
					continue;
				double slope = 0.0, weight = 0.7;
				for (int k = 0; k < nvalid; k++) {
					double resid = targets[k];
					for (int other = 0; other < 4; other++)
						if (other != j)
							resid -= rows[k][other] * gains[other];
					slope += rows[k][j] * resid;
					weight += rows[k][j] * rows[k][j];
				}
				gains[j] = vm_limit(slope / weight, -caps[j], caps[j]);
			}
		}
	}
	double positive = 0.0;
	for (int j = 0; j < 4; j++)
		if (gains[j] > 0)
			positive += gains[j];
	if (positive > 4.98) {
		for (int j = 0; j < 4; j++)
			if (gains[j] > 0)
				gains[j] *= 4.98 / positive;
	}
	vm_curve c;
	c.body = round(gains[0] * 100.0) / 100.0;
	c.mud = round(gains[1] * 100.0) / 100.0;
	c.presence = round(gains[2] * 100.0) / 100.0;
	c.air = round(gains[3] * 100.0) / 100.0;
	double excess = source->speech_spread - reference->speech_spread - 1.0;
	if (excess < 0)
		excess = 0;
	c.ratio = round((1.0 + (excess / 6.0 < 2.0 ? excess / 6.0 : 2.0)) * 100.0) / 100.0;
	c.threshold = round(vm_limit(source->speech_rms70 - 1.5, -32.0, -10.0) * 10.0) / 10.0;
	return c;
}

#endif
