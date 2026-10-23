"""🩺 Whether this machine can be a drive's real host, as the doctor says.

A test that puts a drive on this machine's own bus is marked
`needs_pciem`, and is skipped, saying why, wherever the doctor's `pciem`
area is wanting: on a machine that is not Linux, without pciem loaded,
without sudo that asks no password for the host's commands, or with a
build of socpuppet that has no pciem_host. The last of those is what
keeps the tests from formatting a drive on a machine whose owner did not
set it up for that.
"""

import importlib.util
from pathlib import Path

import pytest

from socpuppet import _core

DOCTOR = Path(__file__).resolve().parents[2] / "tools" / "doctor.py"


def what_pciem_lacks() -> str | None:
    """What this machine or this build lacks to be a real host, if anything."""
    if not _core.has_pciem:
        return "this build has no pciem_host: uv run cmake --preset pciem"
    if not DOCTOR.exists():
        return "the doctor is a checkout's, and this is no checkout"
    spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    (report,) = doctor.examine(
        [area for area in doctor.AREAS if area.name == "pciem"]
    )
    return "; ".join(report.problems) or None


_LACKS = what_pciem_lacks()
needs_pciem = pytest.mark.skipif(
    _LACKS is not None, reason=f"🩺 tools/doctor.py pciem: {_LACKS}"
)
