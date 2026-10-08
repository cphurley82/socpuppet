"""dtc, the devicetree compiler, as a check on devicetree source."""

import os
import shutil
import subprocess

import pytest

needs_dtc = pytest.mark.skipif(
    shutil.which("dtc") is None,
    reason="dtc (the devicetree compiler) is not installed",
)


def dtc_errors(source_text, scratch):
    """Compile devicetree source with dtc and return what it complained about."""
    source = scratch / "platform.dts"
    source.write_text(source_text)
    compiled = subprocess.run(
        ["dtc", "-I", "dts", "-O", "dtb", "-o", os.devnull, str(source)],
        capture_output=True,
        text=True,
    )
    return compiled.stderr
