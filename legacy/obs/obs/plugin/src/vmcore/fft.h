/* vmcore fft.h — iterative radix-2 DIT FFT matching matcher's spectrum():
 * values ordered by bit-reversed input index, twiddles exp(-i*tau*k/size).
 * Self-contained; no allocation (caller owns buffers).
 */
#ifndef VMCORE_FFT_H
#define VMCORE_FFT_H

#include <math.h>
#include <stdint.h>
#include <stdlib.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define VM_FFT_SIZE 2048
#define VM_FFT_HALF (VM_FFT_SIZE / 2 + 1)

typedef struct {
	int reversed_bits[VM_FFT_SIZE];
	double window[VM_FFT_SIZE];
	/* twiddle tables per stage: stages log2(2048)=11, sizes 2..2048 */
	double twiddle_cos[11][VM_FFT_SIZE / 2];
	double twiddle_sin[11][VM_FFT_SIZE / 2];
	/* work buffer */
	double re[VM_FFT_SIZE];
	double im[VM_FFT_SIZE];
} vm_fft;

static void vm_fft_setup(vm_fft *f)
{
	const int bits = 11; /* log2(2048) */
	for (int i = 0; i < VM_FFT_SIZE; i++) {
		int v = 0;
		for (int b = 0; b < bits; b++)
			v |= ((i >> b) & 1) << (bits - 1 - b);
		f->reversed_bits[i] = v;
	}
	for (int i = 0; i < VM_FFT_SIZE; i++)
		f->window[i] = 0.5 - 0.5 * cos(2.0 * M_PI * (double)i / (double)(VM_FFT_SIZE - 1));
	int stage = 0;
	for (int size = 2; size <= VM_FFT_SIZE; size <<= 1, stage++) {
		int half = size >> 1;
		for (int i = 0; i < half; i++) {
			f->twiddle_cos[stage][i] = cos(2.0 * M_PI * (double)i / (double)size);
			f->twiddle_sin[stage][i] = -sin(2.0 * M_PI * (double)i / (double)size);
		}
	}
}

/* Compute magnitudes squared for one channel of a frame.
 * samples: interleaved frame of FFT_SIZE frames * channels floats;
 * channel: which channel to analyze; out: FFT_HALF power bins.
 * NOTE: the oracle (match_voice.py spectrum()) applies the window with the
 * BIT-REVERSED index: values = [samples[rb[i]*ch+off] * window[rb[i]] ...].
 * We replicate that indexing exactly for parity.
 */
static void vm_fft_channel(vm_fft *f, const float *samples, int channels, int channel,
			   double *out_power)
{
	for (int i = 0; i < VM_FFT_SIZE; i++) {
		int rb = f->reversed_bits[i];
		double v = (double)samples[rb * channels + channel] * f->window[rb];
		f->re[i] = v;
		f->im[i] = 0.0;
	}
	int stage = 0;
	for (int size = 2; size <= VM_FFT_SIZE; size <<= 1, stage++) {
		int half = size >> 1;
		for (int start = 0; start < VM_FFT_SIZE; start += size) {
			for (int move = 0; move < half; move++) {
				double wr = f->twiddle_cos[stage][move];
				double wi = f->twiddle_sin[stage][move];
				int low = start + move, high = low + half;
				double xr = f->re[high] * wr - f->im[high] * wi;
				double xi = f->re[high] * wi + f->im[high] * wr;
				double er = f->re[low], ei = f->im[low];
				f->re[low] = er + xr;
				f->im[low] = ei + xi;
				f->re[high] = er - xr;
				f->im[high] = ei - xi;
			}
		}
	}
	for (int i = 0; i < VM_FFT_HALF; i++)
		out_power[i] = f->re[i] * f->re[i] + f->im[i] * f->im[i];
}

#endif
