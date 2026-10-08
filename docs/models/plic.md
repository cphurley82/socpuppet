# Interrupt controller (PLIC)

`sp.Plic()` · C++ `socpuppet::Plic` · registry name `plic`

## What it stands for

The RISC-V platform-level interrupt controller. 🎓 A CPU has one input for "some device wants attention". A platform has many devices. The PLIC sits between: every device's interrupt line goes in, and one line comes out to the CPU.

The firmware and the PLIC then work out which device it was:

1. The firmware gives each source a **priority** and **enables** the ones it wants. A **threshold** masks everything at or below a priority.
2. When an enabled source's line rises, the PLIC raises the CPU's line.
3. The handler reads the **claim** register. It gets the number of the pending source with the highest priority, and the CPU's line drops.
4. When the handler is done it writes that number back, to **complete** it. Until then the same source cannot interrupt again.

## What it does

```python
plic = platform.add("plic", sp.Plic())
bus.map(plic.socket, base=0x0C00_0000)
platform.connect(uart.irq, plic.source1)
platform.connect(plic.irq, cpu.irq)
```

- **31 sources**, `source1` to `source31`, numbered as the PLIC numbers them. Source 0 means "no interrupt". A source nobody connects is tied low.
- **The standard register map**, as in the PLIC specification and as Zephyr's `sifive,plic-1.0.0` driver and QEMU use it: priorities from offset 0, pending bits at `0x1000`, enable bits at `0x2000`, the threshold at `0x20_0000` and claim/complete at `0x20_0004`.
- **Priorities and ties.** The highest priority is claimed first, and of two equal ones the lower source number.
- **Level-sensitive sources.** A source whose line is still high when its handler completes is pending again at once.
- **A request made while the handler runs is remembered.** A source whose line rose after it was claimed is pending again at completion, even if the line has dropped since. 💡 This is for a device whose line only pulses, as a message-signalled interrupt does once it has been turned into a wire: the handler may already have looked, and there is no level left to say so. Two pulses before the claim are one interrupt, and so are any number of them while the handler runs.

## What it leaves out

- **More than one context.** 🎓 A context is one CPU in one privilege mode that can be interrupted. Here there is one: the one CPU, in machine mode. A real PLIC has one per CPU and mode, each with its own enable bits and threshold.
- **A choice of edge or level for each source.** Every source is treated the same way, as above. A real PLIC's sources are wired as one kind or the other. So a level-sensitive device whose line fell and rose again while its handler ran gets one more interrupt after completion, even if the handler already dealt with it. The handler finds nothing to do and returns.
- **A debugger's look at the claim register.** It is declined, because the borrowed model would count it as a claim. Every other register answers a debug access.
- **Timing.** The CPU's line changes in the same instant as the line or register that caused it, give or take a delta cycle: the adapter copies the borrowed model's output through one process of its own, so that the line has exactly one driver however the model reaches it.

## Where it comes from

💡 This one is borrowed. The model is the RISC-V PLIC from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals), written by Minres. socpuppet's adapter (`src/socpuppet/models/plic.cpp`) fixes it at 31 sources and one context and ties off what is not connected.

What socpuppet relies on is written down as tests, in `tests/cpp/contracts/interrupt_controller_contract.h`. They found four bugs and a gap in the borrowed model, written up in [upstream.md](../upstream.md): the last source's priority, a source enabled while already pending, and a line still high at completion, each patched; an output written from two processes at once, which the adapter works around (the timer's adapter does the same); and a request made while its source is claimed, which the specification lets a PLIC forget and a patch makes this one remember.
