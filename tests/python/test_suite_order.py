"""The order this suite's tests are handed out in.

ctest runs the suite on every core with pytest-xdist, which hands the tests
out in the order they were collected. A boot of real firmware takes most of
a minute, so those tests go first: started last, one of them would keep the
whole run waiting while every other core sat idle.
"""

import pytest

# The modules whose tests boot OpenSBI and UEFI.
BOOTS = {"test_m23_exit", "test_m28_exit"}


def test_when_the_boots_are_collected_they_come_before_every_other_test(
    request,
):
    boots = [item.path.stem in BOOTS for item in request.session.items]
    if not any(boots):
        pytest.skip("the boots of OpenSBI and UEFI were not collected")

    assert boots == sorted(boots, reverse=True)
