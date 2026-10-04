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
- **Refuses overlaps.** Two ranges that overlap are refused when you map the second, with a message naming both.
- **Address errors.** An access that hits no range gets an address-error response, and a warning naming the address is logged.
- **DMI and debug.** Both pass through, with addresses translated.

## What it leaves out

- **Bus protocol.** No handshakes, bursts, IDs or channels. A transaction is one function call.
- **Arbitration and timing.** It adds no delay and never makes a master wait for a turn.
- **Security and attributes.** No protection bits, no privilege checks.

## Where it comes from

💡 This one is not ours. It is `scc::router` from [SystemC-Components](https://github.com/Minres/SystemC-Components) (SCC), an open-source library by Minres that is widely used for building virtual platforms. socpuppet registers it behind a small adapter (`src/socpuppet/models/builtin_components.h`) that sizes it and loads the address map.

Its source is worth reading once the idea is clear: [`router.h`](https://github.com/Minres/SystemC-Components/blob/main/src/components/scc/router.h). It can do more than socpuppet uses so far, including several masters and a default target.

⚠️ M0 uses one master per router. Several masters arrive with PCIe in M2, where a device also writes into host memory.
