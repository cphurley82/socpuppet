"""The port of the entropy device's generator agrees with the C++ standard."""

import itertools

from mt19937_64 import numbers

#: The C++ standard's own check of `std::mt19937_64`: the 10000th number
#: from its default seed, 5489 (section [rand.predef]).
STANDARDS_DEFAULT_SEED = 5489
STANDARDS_10000TH_NUMBER = 9981545732273789042


def test_the_ten_thousandth_number_from_the_default_seed_is_the_standards():
    assert (
        next(itertools.islice(numbers(STANDARDS_DEFAULT_SEED), 9999, None))
        == STANDARDS_10000TH_NUMBER
    )
