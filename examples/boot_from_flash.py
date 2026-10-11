"""🧦 A CPU boots from a flash, is reset twice, and boots from it each time.

    compute die                                       IO die
    🧠 cpu ─▶ bus ─┬▶ rom      where the CPU starts
       ▲           ├▶ syscon   where the image is, and why the CPU was reset
       │           ├▶ wdt      the watchdog
       │           ├▶ ram      empty, until the ROM fills it
       │           └▶ link ═══════════════════════════ link ─▶ bus ─▶ flash
       └── reset ── syscon ◀── bite ── wdt                         └▶ uart

In the other examples a CPU wakes up with its firmware already in RAM,
because Python put it there: 🎭 Python is the boot ROM's stand-in, which
is the quick way to try an image. Here the host is described with
`boot=from_rom`, and boots as silicon does. Nothing is loaded into RAM.
The CPU starts in a boot ROM, whose program (firmware/rom) asks the
system controller where its image is, finds it in the flash on the other
die, copies it into RAM, checks it, and jumps to it.

The firmware is a Zephyr application that shows why that matters
(firmware/watchdog). It gets itself reset twice: once by asking, with
`sys_reboot()`, and once by starting its watchdog and then not feeding
it. Each time it starts it reads why from the system controller, and each
time the ROM has to load it again, because a reset leaves nothing in RAM
that can be trusted.

Build the firmware first:      firmware/build.sh
Run it:                        python examples/boot_from_flash.py

The images are looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR
if that is set. With no image there the example says so and counts as
not run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where
a missing image is a failure.

To see where the ROM, the system controller, the watchdog and the flash
are:

    socpuppet address-map examples/boot_from_flash.py
"""

import os
import pathlib
import sys

import socpuppet as sp
from socpuppet import boot_image, transcript
from socpuppet.boards.boot import from_rom
from socpuppet.boards.cpu_kit import BOOT_FLASH_BASE, BOOT_FLASH_SIZE
from socpuppet.boards.host import IO_BASE, host

IMAGES = pathlib.Path(
    os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware")
)
#: The boot ROM's program, built for the host's 64-bit CPU.
ROM = IMAGES / "rom_rv64.elf"
FIRMWARE = IMAGES / "watchdog_socpuppet_host.elf"
#: What the firmware says each time it starts, before why.
RESET_CAUSE = "reset cause: "

# Describe the platform: the host, with a boot ROM for its CPU to start
# in. `trace=True` records everything that crosses the link between the
# dies, which is how the ROM's reads of the flash can be counted below.
board = host(boot=from_rom, trace=True)
#: What `socpuppet devicetree` and `socpuppet address-map` look for.
platform = board.platform


def flash_bytes_read_across_the_link():
    """How many reads of the flash crossed the link, and of how many bytes."""
    # ⚠️ An address in the trace is the IO die's own: the compute die's
    # bus has taken the start of its window off before the access crosses.
    start = BOOT_FLASH_BASE - IO_BASE
    reads = [
        record
        for record in platform.trace
        if record.source == board.link.a.peer_initiator.path
        and record.command == "read"
        and start <= record.address < start + BOOT_FLASH_SIZE
    ]
    return len(reads), sum(len(record.data) for record in reads)


if __name__ == "__main__":
    missing = next(
        (image for image in (ROM, FIRMWARE) if not image.exists()), None
    )
    if missing:
        message = (
            f"There is no {missing} yet. Build the firmware with "
            "`firmware/build.sh`, which takes a few minutes the first time."
        )
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(message)
        print(message)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)

    platform.build()
    # Two things are loaded, and neither into RAM. The ROM's own program
    # goes into the ROM: it is an ELF file that starts where the CPU does.
    platform.load_elf(ROM, via=board.cpu.socket)
    # And the firmware goes into the flash, wrapped: an image is the ELF
    # file's bytes behind a header a ROM can read (docs/models/boot-image.md).
    # The system controller's `boot_address` is where the ROM will look.
    image = boot_image.from_elf(FIRMWARE)
    platform.poke(
        board.syscon.component.boot_address,
        image.to_bytes(),
        via=board.cpu.socket,
    )
    print(
        f"🧦 the power is on. {image.name} is in the flash, "
        f"{len(image.payload)} bytes of it, and the RAM is empty."
    )

    story = sp.Transcript(platform, {"host": board.uart})

    def starts():
        """How many times the firmware has said why it started."""
        return sum(line.text.startswith(RESET_CAUSE) for line in story.lines)

    # The first act: the ROM loads the image, and the firmware starts.
    story.run_until(lambda: starts() == 1, timeout=sp.ms(200))
    reads, read = flash_bytes_read_across_the_link()
    print(
        f"\n📖 the ROM read the flash {reads} times across the link, "
        f"{read} bytes, before anything ran from RAM."
    )

    # The second: the firmware gets itself reset, twice, and is loaded
    # again each time. It takes about 400 ms of simulated time, and the
    # run gives up after a second.
    story.run_until(lambda: starts() == 3, timeout=sp.ms(1000))

    print("\n🖥️  what the console says, with the time of each line:")
    print(transcript.render(story.lines))

    causes = [
        line.text.removeprefix(RESET_CAUSE)
        for line in story.lines
        if line.text.startswith(RESET_CAUSE)
    ]
    if causes != ["power-on", "software", "watchdog"]:
        sys.exit(
            "\n❌ The firmware should have started three times, from "
            f"power-on, its own asking and its watchdog. It said: {causes}"
        )
    reads_in_all, _ = flash_bytes_read_across_the_link()
    print(
        "\n✅ Three starts, and the ROM loaded the image before each: "
        f"{reads_in_all} reads of the flash in all. 💡 What tells the "
        "three apart is the system controller's RESET_CAUSE register, and "
        "nothing the firmware kept. Try it the quick way, with `host()` "
        "and `load_elf` of the firmware, and the second start crashes: "
        "nobody puts the image's data back."
    )
