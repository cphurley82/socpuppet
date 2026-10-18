"""The generator 🎭 the virtio entropy device draws its bytes from.

🎓 `std::mt19937_64` is the 64-bit Mersenne Twister, as the C++ standard
fixes it: the same seed gives the same sequence on every machine, and the
standard says what the ten-thousandth number from its default seed is,
which is how this port is checked (`test_mt19937_64.py`).
"""

W, N, M, R = 64, 312, 156, 31
A = 0xB5026F5AA96619E9
U, D = 29, 0x5555555555555555
S, B = 17, 0x71D67FFFEDA60000
T, C = 37, 0xFFF7EEE000000000
L = 43
F = 6364136223846793005
MASK = (1 << W) - 1
LOWER = (1 << R) - 1
UPPER = MASK ^ LOWER


def numbers(seed):
    """The sequence of 64-bit numbers from `seed`, for ever."""
    state = [seed & MASK]
    for i in range(1, N):
        previous = state[-1]
        state.append((F * (previous ^ (previous >> (W - 2))) + i) & MASK)
    index = N
    while True:
        if index >= N:
            for i in range(N):
                x = (state[i] & UPPER) | (state[(i + 1) % N] & LOWER)
                x_a = x >> 1
                if x & 1:
                    x_a ^= A
                state[i] = state[(i + M) % N] ^ x_a
            index = 0
        y = state[index]
        index += 1
        y ^= (y >> U) & D
        y ^= (y << S) & B
        y ^= (y << T) & C
        y ^= y >> L
        yield y & MASK


def stream(seed, count):
    """The first `count` bytes the entropy device hands out from `seed`.

    Each is the low byte of one number, as `VirtioRngLogic` takes it.
    """
    generator = numbers(seed)
    return bytes(next(generator) & 0xFF for _ in range(count))
