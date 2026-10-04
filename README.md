# socpuppet 🧦

**SoC Puppet** (say "sock puppet") is an open-source virtual platform: a whole system-on-chip simulated on your laptop, with Python pulling the strings.

> 🚧 Early days. The stage is built and the first stand-ins are on it, but there are no CPUs yet, so no firmware runs. The roadmap is in [docs/plan.md](docs/plan.md).

## What's the show?

A chiplet host and an NVMe SSD, each booting its own [Zephyr](https://zephyrproject.org) firmware, inside one SystemC simulation that you compose and drive from Python.

- 🧵 **Python holds the strings.** Compose a platform, load firmware, then run, step, peek, poke and inject faults from a script or a test.
- 🎭 **Every block has a stand-in.** Any CPU, link or device can be swapped for a simpler one that holds its place, so you can study one piece with everything around it simplified.
- 🎓 **Built to teach.** Each model explains the real hardware it represents and what it simplifies.
- 🔧 **Built to use.** Open tools only (SystemC, Zephyr, RISC-V) and tests behind every model, following the way commercial virtual platforms are built.

## A first show

No CPU and no firmware yet, so a script plays the CPU's part: a 🎭 stand-in that carries out bus operations one at a time.

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

```
        0 ns  write 0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
        0 ns  read  0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
        0 ns  read  0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
```

The same description gives the devicetree that firmware will later be built against, with nothing simulated:

```
socpuppet devicetree examples/m0_passthrough.py
```

## Try it

socpuppet is not on PyPI yet, so build it from a checkout. You need a C++20 compiler and [uv](https://docs.astral.sh/uv/); uv brings Python, CMake and Ninja.

```
git clone https://github.com/cphurley82/socpuppet && cd socpuppet
uv sync
uv run cmake --preset dev && uv run cmake --build --preset dev
PYTHONPATH=python uv run python examples/m0_passthrough.py
```

⚠️ The first build compiles SystemC and its companions from source and takes several minutes.

- 💡 [How it is put together](docs/architecture.md), with the vocabulary explained.
- 🔧 [Building and testing](docs/development.md).

## Who's it for?

Anyone curious about how a chip boots before the chip exists. In the spirit of Raspberry Pi, socpuppet aims to be friendly enough to learn on and solid enough to do real work with.
