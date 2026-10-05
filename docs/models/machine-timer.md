# Machine timer

`sp.MachineTimer()` · C++ `socpuppet::MachineTimer` · registry name `machine_timer`

## What it stands for

The timer every RISC-V system has, and the source of an operating system's tick. 🎓 It is two registers. `mtime` counts up at a steady rate, and `mtimecmp` holds a value to compare it with. The timer interrupts for as long as `mtime` is at or past `mtimecmp`. To be woken in 10 ms, the firmware reads `mtime`, adds 10 ms' worth of ticks and writes the sum to `mtimecmp`. Its handler moves `mtimecmp` on again, which ends the interrupt.

The registers sit where SiFive's CLINT has them, which is the layout Zephyr's `riscv,machine-timer` driver and QEMU both use: `mtimecmp` at offset `0x4000` and `mtime` at `0xBFF8`, 64 bits each.

## What it does

```python
timer = platform.add("timer", sp.MachineTimer(frequency_hz=10_000_000))
bus.map(timer.socket, base=0x0200_0000)
platform.connect(timer.irq, cpu.timer_irq)
```

- **Counts simulated time.** `mtime` is the simulated time so far, in ticks of `1 / frequency_hz` seconds. Nothing counts tick by tick: the value is worked out when it is read.
- **Interrupts on time.** `irq` rises at the moment `mtime` reaches `mtimecmp`, with no bus access needed to make it happen, and falls when `mtimecmp` is moved ahead.
- **Takes its registers in halves.** A 32-bit CPU writes each 64-bit register as two words.
- **Stays right when the CPU runs ahead.** 🎓 A CPU model runs ahead of simulated time by up to the platform's quantum. A read of `mtime` from a CPU that is 30 µs ahead gets the count as of 30 µs from now, so the firmware never sees time go backwards.

## What it leaves out

- **The software interrupt** (`msip`), which one CPU uses to interrupt another. The register is there and its output goes nowhere. socpuppet's subsystems have one CPU each.
- **More than one CPU.** One `mtimecmp`, one interrupt.
- **Drift and jitter.** The count is exact.

## Where it comes from

💡 This one is borrowed. The model is the ACLINT from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals), written by Minres, who use it with the same CPU model in their own reference platform. socpuppet's adapter (`src/socpuppet/models/machine_timer.cpp`) gives it its tick rate and exposes the timer interrupt.

What socpuppet relies on is written down as tests, in `tests/cpp/contracts/machine_timer_contract.h`. They found one bug in the borrowed model, a compare value written at time zero that was never acted on, which socpuppet patches (see [upstream.md](../upstream.md)).

⚠️ A CPU sees the interrupt up to one quantum late, because that is how far ahead of simulated time it may be when the interrupt arrives. With the default quantum of 100 µs that is 1% of a 10 ms tick.
