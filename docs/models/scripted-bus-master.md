# 🎭 Scripted bus master

`sp.ScriptedBusMaster(script)` · C++ `socpuppet::ScriptedBusMaster` · registry name `scripted_bus_master`

## What it stands in for

A CPU running firmware. From the rest of the platform's point of view, a CPU is something that issues reads and writes on a bus, reacts to an interrupt and can be held in reset. This stand-in does exactly that much, driven by a script instead of by instructions.

It exists so that buses, memories, links and devices can be built and tested before any CPU model or firmware does.

## What it does

```python
def script():
    yield sp.write32(0x8000_0000, 0xC0FFEE)
    value = yield sp.read32(0x8000_0000)     # a read sends its value back in
    yield sp.expect32(0x8000_0000, 0xC0FFEE) # stops the run if it differs
    yield sp.wait(sp.ns(10))
    yield sp.wait_irq()

cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
```

A script is a Python generator function. Each `yield` hands one operation to the master, which carries it out on the bus.

| Operation | Effect |
|---|---|
| `sp.read32(address)` | Reads 32 bits; the value comes back as the result of the `yield`. |
| `sp.write32(address, value)` | Writes 32 bits. |
| `sp.expect32(address, value)` | Reads, and stops the run with `sp.ExpectationFailed` if the value differs. |
| `sp.wait(duration)` | Lets simulated time pass (`sp.ns(10)`, `sp.us(1)`). |
| `sp.wait_irq()` | Waits until the `irq` input is high. |

It has three ports: `socket` (the bus), and the inputs `irq` and `reset`.

- **Reset.** While `reset` is high the master does nothing. When it is released, the script starts again from the top, as firmware would after a reset.
- **Unconnected inputs** are tied low: no interrupt ever arrives, and the master is never in reset.
- **Errors.** An exception raised in the script comes out of `platform.run()` unchanged.

In C++ the same thing is a C++20 coroutine, which keeps the C++ tests free of Python:

```cpp
socpuppet::Script Boot() {
  co_await socpuppet::Write32(0x10, 0xC0FFEE);
  std::uint32_t value = co_await socpuppet::Read32(0x10);
}
```

## What it leaves out

There is no CPU behind the curtain:

- **No instructions, registers or program counter.** Nothing is fetched or executed.
- **No timing of its own.** Operations take no time unless the script waits.
- **One interrupt line**, level-sensitive, with no controller, priorities or vectors.
- **32-bit accesses only**, little-endian.
- **No DMI.** It makes a transaction for every access, where a CPU model would take a fast path.

🚧 A real CPU (an instruction-set simulator) arrives in milestone M3.
