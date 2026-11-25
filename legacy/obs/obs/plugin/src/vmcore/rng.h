/* vmcore rng.h — MT19937 exactly as CPython's random module initialises it,
 * so the reservoir sampler picks the same frames as matcher/match_voice.py
 * (random.Random(16)). Parity requires bit-identical behaviour.
 */
#ifndef VMCORE_RNG_H
#define VMCORE_RNG_H

#include <stdint.h>

typedef struct {
	uint32_t index;
	uint32_t mt[624];
} vm_rng;

static void vm_rng_init(vm_rng *r, uint32_t seed)
{
	/* CPython random.Random(seed) uses init_by_array([seed]), not the
	 * direct Knuth seed. Verified against CPython 3.12: first five
	 * tempered outputs match exactly. */
	r->mt[0] = 19650218u;
	for (uint32_t i = 1; i < 624; i++)
		r->mt[i] = 1812433253u * (r->mt[i - 1] ^ (r->mt[i - 1] >> 30)) + i;
	uint32_t i = 1, j = 0;
	for (uint32_t k = 624; k > 0; k--) {
		r->mt[i] = (r->mt[i] ^ ((r->mt[i - 1] ^ (r->mt[i - 1] >> 30)) * 1664525u)) + seed;
		i++;
		j++;
		if (i >= 624) {
			r->mt[0] = r->mt[623];
			i = 1;
		}
		if (j >= 1)
			j = 0;
	}
	for (uint32_t k = 623; k > 0; k--) {
		r->mt[i] = (r->mt[i] ^ ((r->mt[i - 1] ^ (r->mt[i - 1] >> 30)) * 1566083941u)) - i;
		i++;
		if (i >= 624) {
			r->mt[0] = r->mt[623];
			i = 1;
		}
	}
	r->mt[0] = 0x80000000u;
	r->index = 624;
}

static void vm_rng_generate(vm_rng *r)
{
	for (uint32_t i = 0; i < 624; i++) {
		uint32_t y = (r->mt[i] & 0x80000000u) | (r->mt[(i + 1) % 624] & 0x7fffffffu);
		r->mt[i] = r->mt[(i + 397) % 624] ^ (y >> 1);
		if (y & 1)
			r->mt[i] ^= 0x9908b0dfu;
	}
	r->index = 0;
}

/* CPython random_random(): genrand_uint32 * (1.0 / 4294967296.0) + 0.5? No:
 * CPython uses (a>>5)*67108864.0+(b>>6) * (1.0/9007199254740992.0).
 * match_voice uses rng.randrange(count): _randbelow_with_getrandbits.
 */
static uint32_t vm_rng_next(vm_rng *r)
{
	if (r->index >= 624)
		vm_rng_generate(r);
	uint32_t y = r->mt[r->index++];
	y ^= y >> 11;
	y ^= (y << 7) & 0x9d2c5680u;
	y ^= (y << 15) & 0xefc60000u;
	y ^= y >> 18;
	return y;
}

static double vm_rng_double(vm_rng *r)
{
	/* CPython genrand_res53: a = next>>5, b = next>>6 */
	uint32_t a = vm_rng_next(r) >> 5;
	uint32_t b = vm_rng_next(r) >> 6;
	return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
}

/* CPython _randbelow(n): k = n.bit_length(); reject on getrandbits(k) >= n.
 * getrandbits(k<=32) = genrand_uint32() >> (32-k), one draw per call.
 * randrange(n) == _randbelow(n) for positive n.
 */
static uint32_t vm_rng_randbelow(vm_rng *r, uint32_t n)
{
	if (n <= 1)
		return 0;
	uint32_t k = 0, m = n;
	while (m) {
		k++;
		m >>= 1;
	}
	for (;;) {
		uint32_t v = vm_rng_next(r) >> (32 - k);
		if (v < n)
			return v;
	}
}

#endif
