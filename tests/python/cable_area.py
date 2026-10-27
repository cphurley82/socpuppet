"""🩺 Whether this machine can plug Linux into its network, as the doctor says.

A test that runs libslirp, or ssh and scp to Linux over it, is marked
`needs_cable`, and is skipped, saying why, wherever the doctor's `cable`
area is wanting. Where the cable must be there, as in CI's nightly runs,
SOCPUPPET_REQUIRE_CABLE=1 fails the run instead, saying why.
"""

import importlib.util
import os
import platform
from pathlib import Path

import pytest

DOCTOR = Path(__file__).resolve().parents[2] / "tools" / "doctor.py"


def what_the_cable_lacks() -> str | None:
    """What this machine lacks for the cable and ssh, if anything."""
    spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    (area,) = [area for area in doctor.AREAS if area.name == "cable"]
    (report,) = doctor.examine([area], platform.system())
    return "; ".join(report.problems) or None


_LACKS = what_the_cable_lacks()
_WHY = f"🩺 tools/doctor.py cable: {_LACKS}"
if _LACKS is not None and os.environ.get("SOCPUPPET_REQUIRE_CABLE"):
    pytest.fail(f"{_WHY}, and SOCPUPPET_REQUIRE_CABLE says it must not")
needs_cable = pytest.mark.skipif(_LACKS is not None, reason=_WHY)
