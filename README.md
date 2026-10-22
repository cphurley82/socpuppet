# socpuppet 🧦

**SoC Puppet** (say "sock puppet") is an open-source virtual platform: a whole system-on-chip simulated on your laptop, with Python pulling the strings.

[![Nightly](https://github.com/cphurley82/socpuppet/actions/workflows/nightly.yml/badge.svg?branch=main)](https://github.com/cphurley82/socpuppet/actions/workflows/nightly.yml) [![CI](https://github.com/cphurley82/socpuppet/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/cphurley82/socpuppet/actions/workflows/ci.yml)

🌙 Every push runs the quick tests on Linux and an Intel Mac; every night runs every test on every machine, Ubuntu and macOS, Intel and Arm. Click a badge for its runs, and a run for each machine's jobs.

> 🚧 Early days, but the show has grown: a chiplet host and an NVMe SSD boot three Zephyr firmwares in one simulation, from a ROM and a flash if you like, with a debugger on each CPU; OpenSBI and UEFI, the firmware a RISC-V server really runs, boot on the host too, and 🐧 Linux boots on them to a shell that you, or Python, can type at, with its root filesystem on the SSD and the SSD's own firmware behind it ([booting Linux](docs/linux.md)). Next on stage, Ethernet ([the roadmap](docs/roadmap.md)).

## What's the show?

A chiplet host and an NVMe SSD, each booting its own [Zephyr](https://zephyrproject.org) firmware, inside one SystemC simulation that you compose and drive from Python.

- 🧵 **Python holds the strings.** Compose a platform, load firmware, then run, step, peek, poke and inject faults from a script or a test.
- 🎭 **Every block has a stand-in.** Any CPU, link or device can be swapped for a simpler one that holds its place, so you can study one piece with everything around it simplified.
- 🎓 **Built to teach.** Each model explains the real hardware it represents and what it simplifies.
- 🔧 **Built to use.** Open tools only (SystemC, Zephyr, RISC-V) and tests behind every model, following the way commercial virtual platforms are built.

## A first show

The host boots [Zephyr](https://zephyrproject.org). It is a 64-bit RISC-V CPU with RAM, a timer and an interrupt controller on one die, and a UART on another.

```python
import socpuppet as sp
from socpuppet.boards.host import host

board = host()                                  # 🧵 describe the platform
board.platform.build()                          # create the simulation
board.platform.load_elf("zephyr.elf")           # firmware built for the board socpuppet_host

board.platform.run_until(
    lambda: "Hello World!" in board.uart.output, timeout=sp.ms(50)
)
print(board.uart.output)
```

```text
*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_host/socpuppet_rv64
```

`uv run firmware/build.py zephyr` builds that `zephyr.elf` (and every other image the tests boot) into `build/firmware`, and `examples/host_hello.py` is this show with the path filled in. The board Zephyr was built for is generated from the same Python description that builds the simulation, so the two cannot disagree about where the UART is. [Boot your firmware here](docs/boot-your-firmware.md) has the steps for an application of your own.

## A smaller show

A platform does not need a CPU. Here a script plays the CPU's part: a 🎭 stand-in that carries out bus operations one at a time.

```python
import socpuppet as sp

RAM = 0x8000_0000

def script():                                  # 🧵 each yield is one bus operation
    yield sp.write32(RAM, 0xC0FFEE)
    value = yield sp.read32(RAM)               # a read sends its value back in
    yield sp.expect32(RAM, value)

platform = sp.Platform()
compute, io = platform.group("compute"), platform.group("io")   # two dies

cpu = compute.add("cpu", sp.ScriptedBusMaster(script))          # 🎭 stands in for the CPU
d2d = platform.link("d2d", sp.PassThroughLink(), compute, io)   # 🎭 stands in for the die-to-die link
bus = io.add("bus", sp.Router())
ram = io.add("ram", sp.Memory(size=64 * 1024))

platform.connect(cpu.socket, d2d.a.target, trace=True)
platform.connect(d2d.b.initiator, bus.target)
bus.map(ram.socket, base=RAM)

platform.build()
platform.run()
print(sp.render_trace(platform.trace))
```

```text
        0 ns  write 0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
        0 ns  read  0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
        0 ns  read  0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
```

And now for something completely different: the same description also gives the devicetree that firmware is built against, with nothing simulated.

```sh
socpuppet devicetree examples/m0_passthrough.py
```

And its address map, which is what answers at which address and through which window:

```sh
socpuppet address-map examples/m0_passthrough.py
```

## A show with a drive in it

A script can also play the host's driver. Here it finds an NVMe drive over PCIe and uses it. 🎭 The drive is a stand-in that answers for itself, but the PCIe in between is real enough to matter: nothing can be read until the script has found the drive, given its registers a place in memory and said where its interrupts go.

```python
def script():
    pci = sp.PcieHost(ecam=ECAM_BASE)
    msi = sp.MsiHost(receiver=MSI_BASE)
    (drive,) = yield from pci.scan()                    # find it
    yield from pci.place(drive, WINDOW_BASE)            # place its registers
    yield from pci.route_interrupts(drive, to=msi)      # route its interrupts

    nvme = sp.NvmeHost(registers=WINDOW_BASE, memory=RAM_BASE, interrupt=msi.wait)
    yield from nvme.enable()
    yield from nvme.write_blocks(first=7, data=block)
    read_back = yield from nvme.read_blocks(first=7, count=1)
```

The platform around it, split over two dies, is in `examples/nvme_hello.py`.

The rest of the cast arrives one example at a time. Each swaps one 🎭 stand-in for the real thing, and the scripts around it do not change by a line.

| Example | What it shows |
|---|---|
| `examples/ssd_hello.py` | The drive is built like an SSD: hardware for the queues and the data, a NAND chip, and 🎭 a short Python script for its firmware, which is the place to read what an SSD does with a write |
| `examples/ssd_firmware_hello.py` | The script gives way to the SSD's own CPU and its real firmware, a Zephyr application in `firmware/ssd` |
| `examples/host_and_ssd_hello.py` | The host is a 64-bit CPU running Zephyr and its SSD a 32-bit CPU running Zephyr, sharing one simulation and one clock; both consoles printed as one story |
| `examples/chiplet_host_hello.py` | The host starts up the way a chiplet does: the IO die's manager trains the link between the dies, packet by packet, and lets the host's CPU out of reset |
| `examples/full_bootchain.py` | No script left: three CPUs run three Zephyr images, and the three consoles tell the boot as one story, each line with who said it and when |
| `examples/shell_from_python.py` | The puppet answers back: Python types at Zephyr's shell and reads what it says, with the console's interrupt crossing the dies as a message |
| `examples/boot_from_flash.py` | Booting the way silicon does: the CPU starts in a boot ROM, finds the firmware in a flash on the other die, checks it and jumps, and the watchdog resets it twice |

## Try it

socpuppet is not on PyPI yet, so build it from a checkout. You need a C++20 compiler and [uv](https://docs.astral.sh/uv/); uv brings Python, CMake and Ninja.

```sh
git clone https://github.com/cphurley82/socpuppet && cd socpuppet
uv sync
uv run cmake --preset dev && uv run cmake --build --preset dev
PYTHONPATH=python uv run python examples/m0_passthrough.py
PYTHONPATH=python uv run python examples/nvme_hello.py
PYTHONPATH=python uv run python examples/ssd_hello.py
```

⚠️ The first build compiles SystemC and its companions from source and takes several minutes.

🐧 To boot Linux and type at its shell yourself, build the firmware first (`uv run firmware/build.py`, which takes a while the first time), then:

```sh
PYTHONPATH=python uv run python -m socpuppet linux
```

- 🧭 [Why socpuppet exists](docs/vision.md): who it is for, the aims, and how choices get made.
- 🚀 [Boot your firmware here](docs/boot-your-firmware.md): your own Zephyr application on the host, with a debugger on it.
- 💡 [How it is put together](docs/architecture.md), with the vocabulary explained and a page for every model.
- 🛠️ [Setting up a machine for development](docs/setup.md), from a bare install to every test passing.
- 📚 [All the docs](docs/README.md), by the reader they are written for.

## Who's it for?

Anyone curious about how a chip boots before the chip exists. In the spirit of Raspberry Pi, socpuppet aims to be friendly enough to learn on and solid enough to do real work with. It is written for a ladder of readers, bottom rung first:

- 🌱 Someone who knows a little Python and has never seen a chip from the inside. 🚧 Not served yet: a first page that needs nothing but Python is on the list for the first release.
- 🎓 The learner building a first virtual platform.
- 🧵 The firmware developer who installs a board with pip and boots their image on it.
- The engineer who builds virtual platforms for a living and wants methodology to take home.

[Why socpuppet exists](docs/vision.md) has the aims, and the rules that decide what gets built next.
