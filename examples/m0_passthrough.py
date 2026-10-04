"""🧦 The smallest puppet show: a scripted CPU stand-in, a link, and a RAM.

    compute die                                IO die
    🎭 scripted master ─▶ link endpoint ══ link endpoint ─▶ router ─▶ memory

There is no CPU and no firmware here. The "CPU" is a stand-in that carries
out a Python script of bus operations, and the die-to-die link is a stand-in
that passes everything straight through. The rest (the router and the
memory) is real, so this is already enough to rehearse a memory map.

Run it:                    python examples/m0_passthrough.py
See its devicetree:        socpuppet devicetree examples/m0_passthrough.py
"""

import socpuppet as sp

RAM_BASE = 0x8000_0000


def script():
    """What the stand-in CPU does. Each `yield` is one bus operation."""
    yield sp.write32(RAM_BASE, 0xC0FFEE)
    yield sp.wait(sp.ns(10))
    value = yield sp.read32(RAM_BASE)  # a read sends its value back in
    yield sp.write32(RAM_BASE + 4, value + 1)
    yield sp.expect32(RAM_BASE + 4, 0xC0FFEF)


# Describe the platform. Nothing is simulated yet, which is why the
# devicetree command can load this file without running anything.
platform = sp.Platform()
compute = platform.group("compute")
io = platform.group("io")

cpu = compute.add("cpu", sp.ScriptedBusMaster(script))
d2d = platform.link("d2d", sp.PassThroughLink(), compute, io)
bus = io.add("bus", sp.Router())
ram = io.add("ram", sp.Memory(size=64 * 1024))

platform.connect(cpu.socket, d2d.a.target, trace=True)  # watch what crosses onto the link
platform.connect(d2d.b.initiator, bus.target)
bus.map(ram.socket, base=RAM_BASE)

if __name__ == "__main__":
    platform.build()  # the simulation exists from here on, and the wiring is fixed
    platform.run()

    print(sp.render_trace(platform.trace))
    print(f"\n✅ The show ran for {platform.time // sp.ns(1)} ns of simulated time.")
    print(f"   RAM now holds {platform.peek32(RAM_BASE):#x} and {platform.peek32(RAM_BASE + 4):#x}.")
