# CPU (DBT-RISE-RISCV)

`sp.DbtRiseCpu(xlen=64, reset_vector=...)` · C++ `socpuppet::DbtRiseCpu` · registry name `dbt_rise_cpu`

## What it stands for

A RISC-V processor core: the thing that runs the firmware. 🎓 The model is an **instruction-set simulator** (ISS). It does what the processor does, one instruction after another: fetch the instruction at the program counter, work out what it means, carry it out, move on. It models what a program can observe (registers, memory, traps, interrupts) and not how the silicon gets there. There is no pipeline, cache or branch predictor inside.

## What it does

```python
cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=64, reset_vector=0x8000_0000))
platform.connect(cpu.socket, bus.target)
platform.connect(plic.irq, cpu.irq)
platform.connect(timer.irq, cpu.timer_irq)

platform.build()
platform.load_elf("zephyr.elf")
platform.run(sp.ms(100))
```

- **RV32IMAC or RV64IMAC**, chosen by `xlen`: the base integer instructions, multiply and divide, atomics and compressed instructions, with the control registers (`zicsr`) and `fence.i` (`zifencei`). Build firmware with `-march=rv64imac_zicsr_zifencei`, or `rv32imac...`.
- **Machine mode**, with physical memory protection (PMP), which is what Zephyr uses on small cores.
- **Starts at its reset vector.** `load_elf` checks that the image starts there and was built for the same word size.
- **Three inputs.** `irq` is the machine external interrupt, for the interrupt controller. `timer_irq` is the machine timer interrupt. `reset` holds the core while it is high and restarts it from the reset vector when it drops.
- **Takes one clock period per instruction.** The clock is 10 MHz, so an instruction is 100 ns of simulated time, whatever it is.
- **Can be debugged.** With `gdb_port=1234` the CPU listens for GDB on that port and waits for it to attach before the first instruction. See [boot-your-firmware.md](../boot-your-firmware.md).
- **Sleeps properly.** In `wfi` (wait for interrupt) the core does nothing at all until an interrupt arrives, so an idle system costs almost nothing to simulate.

## What makes it fast

🎓 Two things, and both are worth knowing because every virtual platform has them.

**Direct memory access (DMI).** The first time the core reads from a RAM, it asks the RAM for a pointer to its bytes. From then on it reads and writes them directly, with no bus transaction. Only devices, which have to notice each access, are reached over the bus. ⚠️ A traced connection refuses DMI, so do not trace the path from a CPU to its main memory and expect speed.

**Temporal decoupling.** The core runs many instructions in one go and only then lets the rest of the platform catch up. How far ahead it may get is the platform's `quantum`, 100 µs by default. The price is that the core sees an interrupt up to a quantum late. On a loop of two million instructions the core ran at 9 million instructions a second with no quantum and 44 million with the default.

## What it leaves out

- **Floating point**, supervisor and user modes, and virtual memory. None of the firmware here needs them. DBT-RISE has cores with all of them, and socpuppet does not offer them yet.
- **Cycle accuracy.** Every instruction takes the same time. Use it to find out what firmware does, not how many nanoseconds it takes.
- **Faster backends.** DBT-RISE can also translate blocks of RISC-V code into host code. socpuppet uses its interpreter.
- **More than one debugger.** Only one CPU in a simulation can have a GDB port: DBT-RISE has one GDB server per process.

## Where it comes from

💡 This one is borrowed. The model is [DBT-RISE-RISCV](https://github.com/Minres/DBT-RISE-RISCV) by Minres, on their [DBT-RISE-Core](https://github.com/Minres/DBT-RISE-Core). socpuppet wraps it in a small adapter (`src/socpuppet/models/dbt_rise_cpu.cpp`) that joins its two bus sockets (one for fetching instructions, one for data) into one, gives it its clock, and exposes the three inputs.

Why this one, and what else was tried, is in the [ISS spike report](../iss-spike.md).

### Reading it

⚠️ Most of DBT-RISE's CPU is generated code, which is not written to be read from top to bottom. If you want to see how an instruction is executed:

- The instructions are described in a language called CoreDSL, and `src/vm/interp/vm_rv64imac.cpp` is generated from that description: a table of bit patterns, then one `case` per instruction. Pick one, such as `ADDI`, and read its case: decode the fields, compute, write the register.
- What happens around the instructions is hand-written C++ in `src/iss/arch/riscv_hart_m_p.h` and `riscv_hart_common.h`: how a trap is taken, what the control registers do, how an interrupt is noticed.
- How the core sits in a SystemC simulation is `src/sysc/core_complex.cpp`: where time is kept, how memory is reached, where DMI comes in.

### What we changed

socpuppet holds the CPU to the same contract as the scripted stand-in (`tests/cpp/contracts/bus_master_contract.h`) and to tests of its own (`tests/cpp/platform/cpu_test.cpp`). They found three bugs, each patched: a reset raised a second time stopped the simulation, a withdrawn DMI grant was ignored, and an interrupt handler was entered over and over. Four more patches are for compilers and build systems. All seven are written up in [upstream.md](../upstream.md).
