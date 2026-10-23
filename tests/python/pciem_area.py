"""🩺 Whether this machine can be a drive's real host, as the doctor says.

A test that puts a drive on this machine's own bus is marked
`needs_pciem`, and is skipped, saying why, wherever the doctor's `pciem`
area is wanting: on a machine that is not Linux, without pciem loaded,
without sudo that asks no password for the host's commands, or with a
build of socpuppet that has no pciem_host. The last of those is what
keeps the tests from formatting a drive on a machine whose owner did not
set it up for that. A test that only opens /dev/pciem, and runs nothing
as root, is marked `needs_dev_pciem` and asks less: the same, but for
sudo. Where pciem must be there, as in CI's guest (tools/pciem_guest.py),
SOCPUPPET_REQUIRE_PCIEM=1 fails the run instead, saying why.
"""

import dataclasses
import importlib.util
import os
from pathlib import Path

import pytest

from socpuppet import _core

DOCTOR = Path(__file__).resolve().parents[2] / "tools" / "doctor.py"


def what_pciem_lacks(*, as_root: bool = True) -> str | None:
    """What this machine or this build lacks to be a real host, if anything.

    Without `as_root`, what it lacks to open /dev/pciem alone: the
    doctor's needs of sudo are left out.
    """
    if not _core.has_pciem:
        return "this build has no pciem_host: uv run cmake --preset pciem"
    if not DOCTOR.exists():
        return "the doctor is a checkout's, and this is no checkout"
    spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    (area,) = [area for area in doctor.AREAS if area.name == "pciem"]
    needs = doctor.PCIEM if as_root else doctor.PCIEM_DEVICE
    (report,) = doctor.examine([dataclasses.replace(area, needs=needs)])
    return "; ".join(report.problems) or None


_LACKS = what_pciem_lacks()
_WHY = f"🩺 tools/doctor.py pciem: {_LACKS}"
if _LACKS is not None and os.environ.get("SOCPUPPET_REQUIRE_PCIEM"):
    pytest.fail(f"{_WHY}, and SOCPUPPET_REQUIRE_PCIEM says it must not")
needs_pciem = pytest.mark.skipif(_LACKS is not None, reason=_WHY)

_DEV_LACKS = what_pciem_lacks(as_root=False)
needs_dev_pciem = pytest.mark.skipif(
    _DEV_LACKS is not None, reason=f"🩺 tools/doctor.py pciem: {_DEV_LACKS}"
)
