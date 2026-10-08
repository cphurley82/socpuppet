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
| `sp.read(address, length)` | Reads `length` bytes in one access; they come back as `bytes`. |
| `sp.write(address, data)` | Writes the bytes of `data` in one access. |
| `sp.expect32(address, value)` | Reads, and stops the run with `sp.ExpectationFailed` if the value differs. |
| `sp.wait(duration)` | Lets simulated time pass (`sp.ns(10)`, `sp.us(1)`). |
| `sp.wait_irq()` | Waits until the `irq` input is high. |

It has three ports: `socket` (the bus), and the inputs `irq` and `reset`.

- **Reset.** While `reset` is high the master does nothing. When it is released, the script starts again from the top, as firmware would after a reset.
- **Unconnected inputs** are tied low: no interrupt ever arrives, and the master is never in reset.
- **A refused access stops the run.** A read or write that nothing answers, or that the target will not take, comes out of `platform.run()` as `sp.BusError`, naming the address and the bus's response. ⚠️ A real CPU would take a bus fault or read garbage; the stand-in is stricter, because a script that reads zeros from nowhere is a bug waiting to be found.
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
- **No timing of its own.** An operation takes as long as the device it reaches says it takes, and no longer. Most devices here say "no time at all", so time only passes when the script waits.
- **One interrupt line**, level-sensitive, with no controller, priorities or vectors.
- **Every access gets a turn to take effect.** After each read or write the stand-in lets up to two delta cycles pass, as the real CPU does, so that a line the access lowered is seen low by whatever watches it before the script's next access. 💡 That is what lets a script claim an interrupt at a PLIC, quiet the device and complete the interrupt without being interrupted a second time: the PLIC sees the device go quiet before the completion arrives.
- **Beats.** `read32` and `write32` are little-endian 32-bit accesses. `read` and `write` move any number of bytes in one transaction. A real CPU would need several accesses or a burst for anything wider than its bus. The stand-in sends it whole, which is how a loosely-timed model writes a burst, with no beat-by-beat timing. There are no byte enables.
- **No DMI.** It makes a transaction for every access, where a CPU model would take a fast path.

## What it shares with a real CPU

The stand-in fills the same slot as the real CPU, `sp.DbtRiseCpu`, and is held to the same contract (`tests/cpp/contracts/bus_master_contract.h`): how reset holds and restarts it, how it waits for its interrupt, how it takes interrupts through a PLIC, and how it keeps time.

🎓 That last one is temporal decoupling. A master may run ahead of simulated time by up to the platform's `quantum`, and only then lets everything else catch up. When a device says an access took 3 µs, the stand-in adds that to how far ahead it is, and stops to let the clock catch up once it is a whole quantum ahead, before it waits for something, and when its script ends.
