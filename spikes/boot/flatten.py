"""Question 3, second half: is an ELF's segments laid end to end `zephyr.bin`?

M14's image tool wraps an ELF. A ROM copies flat bytes. If the segments,
each at its physical address counted from the lowest, are what objcopy
made of the same ELF, then the tool needs only the ELF.

Run it:    PYTHONPATH=python uv run python spikes/boot/flatten.py
"""

import pathlib

from socpuppet import _core

for elf in sorted(pathlib.Path("build/firmware").glob("*.elf")):
    xlen, entry, loaded = _core.read_elf(str(elf))
    segments = [(address, data) for address, data in loaded if data]
    base = min(address for address, _ in segments)
    end = max(address + len(data) for address, data in segments)
    flat = bytearray(end - base)
    for address, data in segments:
        flat[address - base : address - base + len(data)] = data
    binary = elf.with_suffix(".bin").read_bytes()
    differing = [
        at
        for at in range(min(len(flat), len(binary)))
        if flat[at] != binary[at]
    ]
    # A gap between sections is zero in an ELF's segment and 0xFF in the
    # .bin, which is what Zephyr has objcopy fill a gap with.
    only_gaps = len(flat) == len(binary) and all(
        (flat[at], binary[at]) == (0, 0xFF) for at in differing
    )
    print(
        "✅" if only_gaps else "❌",
        elf.name,
        f"rv{xlen}, {len(segments)} segment(s), {len(flat)} bytes flattened,",
        f"{len(binary)} in the .bin, {len(differing)} bytes of gap differ",
    )
