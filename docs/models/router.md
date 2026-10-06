# Router

`sp.Router()` · C++ `scc::router` · registry name `router`

## What it stands for

The address decoder of a bus: the logic that looks at an address and decides which device the access is for. On real hardware this is part of an interconnect such as AXI.

## What it does

```python
bus = platform.add("bus", sp.Router())
platform.connect(cpu.socket, bus.target)
bus.map(ram.socket, base=0x8000_0000)
```

- **Routes by address.** `map(target, base)` routes the range starting at `base`, as long as the target is, to that target.
- **Translates.** The target sees addresses as offsets from `base`. A RAM mapped at `0x8000_0000` receives an access to `0x8000_0010` as offset `0x10`.
- **Takes several sources of accesses.** The first connects to `bus.target`. Each one after that gets an input of its own: `platform.connect(device.dma, bus.add_input())`. Every input sees the same address map. A device that does DMA (direct memory access: it reads and writes the host's memory itself, without the CPU copying anything) needs an input too.
- **Refuses overlaps.** Two ranges that overlap are refused when you map the second, with a message naming both.
- **Address errors.** An access that hits no range gets an address-error response, and a warning naming the address is logged.
- **DMI and debug.** Both pass through, with addresses translated.

## What it leaves out

- **Bus protocol.** No handshakes, bursts, IDs or channels. A transaction is one function call.
- **Arbitration and timing.** It adds no delay, and there are no priorities or fairness. 💡 It does keep two masters out of one target at the same time: if an access is still inside a target that takes simulated time, a second master's access to that target waits until the first has finished. Every target in socpuppet answers at once so far, so nobody waits.
- **Security and attributes.** No protection bits, no privilege checks.

## Where it comes from

💡 This one is not ours. It is `scc::router` from [SystemC-Components](https://github.com/Minres/SystemC-Components) (SCC), an open-source library by Minres that is widely used for building virtual platforms. socpuppet registers it behind a small adapter (`src/socpuppet/models/builtin_components.h`) that sizes it and loads the address map.

Its source is worth reading once the idea is clear: [`router.h`](https://github.com/Minres/SystemC-Components/blob/main/src/components/scc/router.h). It can do more than socpuppet uses so far, including a default target and a different base address per master.
