"""Boots an image on the standalone QBox platform and times it.

Run inside the QBox container, after build.sh:

    python3 measure.py <xlen> <image> <mode> <text to wait for>

It starts QBox's `platforms-vp` on zephyr.lua, waits for the text to appear
on the UART, and prints how long that took from the moment the simulation
started (the "SC_START" line), leaving out the time QBox takes to load.
"""

import os
import pathlib
import pty
import select
import subprocess
import sys
import time

VP = "/qbox/src/build/platforms-vp"
HERE = pathlib.Path(__file__).parent


def main() -> int:
    """Runs one measurement and prints it. Returns the exit status."""
    xlen, image, mode, marker = sys.argv[1:5]
    environment = os.environ | {
        "SPIKE_XLEN": xlen,
        "SPIKE_IMAGE": image,
        "SPIKE_MODE": mode,
    }
    # QBox only writes as it goes when it thinks it is talking to a
    # terminal, so give it one.
    terminal, child_side = pty.openpty()
    launched = time.monotonic()
    process = subprocess.Popen(
        [VP, "--gs_luafile", str(HERE / "zephyr.lua")],
        env=environment,
        stdin=child_side,
        stdout=child_side,
        stderr=child_side,
    )
    os.close(child_side)
    output = b""
    started = None
    found = None
    while time.monotonic() - launched < 300:
        if not select.select([terminal], [], [], 1.0)[0]:
            continue
        try:
            chunk = os.read(terminal, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if started is None and b"SC_START" in output:
            started = time.monotonic()
        # Only what comes after the start counts: the banner before it has
        # plenty of letters in it.
        after_start = output.partition(b"SC_START")[2]
        if marker.encode() in after_start:
            found = time.monotonic()
            break
    process.kill()
    process.wait()
    if found is None or started is None:
        print(
            f"{marker!r} never appeared. Output:\n{output.decode(errors='replace')}"
        )
        return 1
    print(
        f"RV{xlen} {mode}: {marker!r} after {found - started:.3f} s"
        f" (QBox took {started - launched:.3f} s to load)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
