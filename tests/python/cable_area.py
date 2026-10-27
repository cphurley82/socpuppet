"""🔌 Whether this machine can plug Linux into its network, as the package says.

A test that runs libslirp, or ssh and scp to Linux over it, is marked
`needs_cable`, and is skipped, saying why, wherever this machine lacks
libslirp, ssh or scp. The package itself is asked, as the tests use it,
so the wheel's run, a copy of these tests with no checkout beside them,
asks the same. Where the cable must be there, as in CI's nightly runs,
SOCPUPPET_REQUIRE_CABLE=1 fails the run instead, saying why.
"""

import os
import shutil

import pytest

from socpuppet import SlirpUnavailable, slirp


def what_the_cable_lacks() -> str | None:
    """What this machine lacks for the cable and ssh, if anything."""
    try:
        slirp.version()
    except SlirpUnavailable as unavailable:
        # The package says what is missing and how to install it.
        return str(unavailable).removeprefix("🩺 ")
    for program in ("ssh", "scp"):
        if not shutil.which(program):
            return f"{program} is not installed"
    return None


_LACKS = what_the_cable_lacks()
_WHY = f"🔌 the cable: {_LACKS}"
if _LACKS is not None and os.environ.get("SOCPUPPET_REQUIRE_CABLE"):
    pytest.fail(f"{_WHY}, and SOCPUPPET_REQUIRE_CABLE says it must not")
needs_cable = pytest.mark.skipif(_LACKS is not None, reason=_WHY)
