# socpuppet 🧦

**SoC Puppet** (say "sock puppet") is an open-source virtual platform: a whole system-on-chip simulated on your laptop, with Python pulling the strings.

> 🚧 Early days. Two acts are up: a RISC-V host that boots Zephyr, and a scripted host that finds a stand-in NVMe drive over PCIe and reads and writes it. They have met, too: Zephyr on the host finds the same drive and uses it with its own NVMe driver. The real SSD with its own firmware and the real die-to-die link are still to come. The roadmap is in [docs/plan.md](docs/plan.md).

## What's the show?

A chiplet host and an NVMe SSD, each booting its own [Zephyr](https://zephyrproject.org) firmware, inside one SystemC simulation that you compose and drive from Python.

- 🧵 **Python holds the strings.** Compose a platform, load firmware, then run, step, peek, poke and inject faults from a script or a test.
- 🎭 **Every block has a stand-in.** Any CPU, link or device can be swapped for a simpler one that holds its place, so you can study one piece with everything around it simplified.
- 🎓 **Built to teach.** Each model explains the real hardware it represents and what it simplifies.
- 🔧 **Built to use.** Open tools only (SystemC, Zephyr, RISC-V) and tests behind every model, following the way commercial virtual platforms are built.

## A first show

The host boots [Zephyr](https://zephyrproject.org). It is a 64-bit RISC-V CPU with RAM and an interrupt controller on one die, and a UART and a timer on another.

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

The board Zephyr was built for is generated from the same Python description that builds the simulation, so the two cannot disagree about where the UART is. [Boot your own firmware](docs/boot-your-firmware.md) has the steps.

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

## Try it

socpuppet is not on PyPI yet, so build it from a checkout. You need a C++20 compiler and [uv](https://docs.astral.sh/uv/); uv brings Python, CMake and Ninja.

```sh
git clone https://github.com/cphurley82/socpuppet && cd socpuppet
uv sync
uv run cmake --preset dev && uv run cmake --build --preset dev
PYTHONPATH=python uv run python examples/m0_passthrough.py
PYTHONPATH=python uv run python examples/nvme_hello.py
```

⚠️ The first build compiles SystemC and its companions from source and takes several minutes.

- 🚀 [Boot your own firmware](docs/boot-your-firmware.md) on the host board.
- 💡 [How it is put together](docs/architecture.md), with the vocabulary explained.
- 🔧 [Building and testing](docs/development.md).
- 🎨 [Style, and the tools that hold us to it](docs/style.md).
- 📮 [What we owe upstream](docs/upstream.md): the fixes we carry for the projects we borrow from.

## Who's it for?

Anyone curious about how a chip boots before the chip exists. In the spirit of Raspberry Pi, socpuppet aims to be friendly enough to learn on and solid enough to do real work with.
