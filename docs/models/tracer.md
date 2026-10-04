# Tracer

`platform.connect(a, b, trace=True)` · C++ `socpuppet::Tracer`

## What it is

Not a model of any hardware. It is a probe: it sits on one connection and records every transaction that crosses it, like a protocol analyzer clipped onto a bus.

## What it does

```python
platform.connect(cpu.socket, d2d.a.target, trace=True)
platform.run()
print(sp.render_trace(platform.trace))
```

```text
        0 ns  write 0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
       10 ns  read  0x80000000  ee ff c0 00  ✅  compute.cpu.socket → compute.d2d.target
```

Each record holds the time, the two ports, the command, the address as the initiator sent it, the data and whether the target answered without error.

- `platform.trace` is a list of `sp.TraceRecord`, for tests.
- `sp.render_trace(records)` is for people. It uses color only on a terminal, and never when `NO_COLOR` is set.
- `socpuppet.trace.to_json_lines(records)` is for machines: one JSON object per line, plain.

## Two things to know

⚠️ **A traced connection refuses DMI.** DMI hands the initiator a pointer so that later accesses skip the bus, and an access that skips the bus skips the tracer too. Refusing keeps every access visible. The price is speed, which is the right trade for a connection you asked to watch, and a reason not to trace a CPU's path to its main memory.

💡 **Debug accesses are not recorded.** A `peek` or `poke` passes through, but it is you looking in, not the platform's own traffic.

## What it leaves out

- **Wires.** Only bus connections can be traced; asking to trace a wire is refused.
- **Filtering and limits.** Every transaction is kept in memory for the whole run.
