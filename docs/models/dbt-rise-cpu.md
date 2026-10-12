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

- **RV32IMAC or RV64IMAC**, chosen by `xlen`: the base integer instructions, multiply and divide, atomics and compressed instructions, with the control registers (`zicsr`) and `fence.i` (`zifencei`). Build firmware with `-march=rv64imac_zicsr_zifencei`, or `rv32imac...`. It has **machine mode**, with physical memory protection (PMP), which is what Zephyr uses on small cores.
- **Or RV64GC with supervisor and user mode**: `sp.DbtRiseCpu(xlen=64, isa="gc", modes="msu", ...)`. 🎓 G is IMA with single and double floating point (F and D), and with C it is what an application processor has and what Linux needs. This is the host's core. ⚠️ It has no PMP. The two are the cores socpuppet offers, and any other combination is refused by name.
- **On that core, what an operating system needs of a hart**, each held by tests that run a small program doing the one thing (`tests/cpp/platform/cpu_test.cpp`):
  - **Paging, Sv39.** 🎓 A kernel gives each program addresses of its own, and tables that say which page of real memory each page of those is. The hart walks the tables for every instruction it fetches and every word it loads or stores, and keeps what it found (in a **TLB**) until `sfence.vma` tells it to forget. Pages of 4 KiB, 2 MiB and 1 GiB. A page that is not mapped, or not allowed for that use, is a page fault that says which address.
  - **User mode**, under supervisor mode: a program's `ecall` is a system call that the kernel's handler takes, and what belongs to the modes above it (`sret`, `mret`, `sfence.vma`, the kernel's registers) is an illegal instruction there.
  - **The counters, by leave.** `cycle`, `time` and `instret` can be read below machine mode only if `mcounteren` allows it, and in user mode only if `scounteren` does too. Linux gives its programs `time` that way, for the time of day with no system call.
  - **Floating point that says when it has been used.** With `FS` off in the status register a floating-point instruction traps, and with it on the first one leaves it dirty, which is how a kernel knows whose registers to save.
  - **Atomics**: `lr` and `sc`, with one reservation that any `sc` gives up, and the `amo*` instructions.
  - **Traps that leave a handler what it needs**: the cause, the address, and the instruction to come back to, for a monitor in machine mode or handed down to the kernel in `medeleg` and `mideleg`.
- **Starts at its reset vector**, in machine mode. `load_elf` checks that the image starts there and was built for the same word size. On a socpuppet board that is the start of RAM, or with `boot=from_rom` the [boot ROM](rom.md), and then again every time its `reset` falls: after a watchdog's bite, or when firmware asks its [system controller](system-controller.md) for a reset.
- **Four inputs.** `irq` is the machine external interrupt, for the interrupt controller. `timer_irq` is the machine timer interrupt. `supervisor_irq` is the supervisor external interrupt, which a core with supervisor mode takes when machine mode has handed it down (`mideleg`). `reset` holds the core while it is high and restarts it from the reset vector when it drops.
- **Reads the timer's count as its own `time` register**, if its `time` is connected to a [machine timer](machine-timer.md)'s. Left unconnected, `time` reads as zero.
- **Reaches an IMSIC's registers through its own**, if its `csr` is connected to an [IMSIC](imsic.md)'s. 🎓 An IMSIC's registers are not on the bus. Firmware selects one by writing its number to the CPU's `miselect` register and then finds it at `mireg`, and claims an interrupt at `mtopei`. Those three are machine mode's. A core with supervisor mode has three more for the IMSIC's other interrupt file, `siselect`, `sireg` and `stopei`, which are what an operating system under a monitor uses, and each mode selects for itself. Unconnected, all of them are illegal instructions, as on a core with no IMSIC. The devicetree's `cpu` node lists `smcsrind` only when `csr` is connected, and `ssaia` beside it if the core has supervisor mode.
- **Takes one clock period per instruction.** The clock is 10 MHz, so an instruction is 100 ns of simulated time, whatever it is.
- **Can be debugged.** With `gdb_port=1234` the CPU listens for GDB on that port and waits for it to attach before the first instruction. Each CPU of a simulation can have a port of its own, and a debugger each. See [boot-your-firmware.md](../boot-your-firmware.md).
- **Sleeps properly.** In `wfi` (wait for interrupt) the core does nothing at all until an interrupt arrives, so an idle system costs almost nothing to simulate.

## What makes it fast

🎓 Two things, and both are worth knowing because every virtual platform has them.

**Direct memory access (DMI).** The first time the core reads from a RAM, it asks the RAM for a pointer to its bytes. From then on it reads and writes them directly, with no bus transaction. Only devices, which have to notice each access, are reached over the bus. ⚠️ A traced connection refuses DMI, so do not trace the path from a CPU to its main memory and expect speed.

**Temporal decoupling.** The core runs many instructions in one go and only then lets the rest of the platform catch up. How far ahead it may get is the platform's `quantum`, 100 µs by default. The price is that the core sees an interrupt up to a quantum late. On a loop of two million instructions the core ran at 9 million instructions a second with no quantum and 44 million with the default.

## What it leaves out

- **The other cores DBT-RISE has.** It has many more combinations of extensions and modes than the two here.
- **Paging beyond Sv39, and address-space identifiers.** `satp` keeps Sv39 and nothing bigger, and its identifier field reads as zero, so a kernel empties the TLB when it changes program. Most chips are the same. ⚠️ The borrowed MMU has Sv48 and Sv57 in it, switched off because nothing here has run them ([upstream.md](../upstream.md) says how to have them back).
- **Marking pages itself.** 🎓 A page's entry has a bit for "used" and a bit for "written", and a hart may set them as it goes or leave that to the kernel. This one leaves it: a page whose bit is clear is a page fault, and the kernel sets the bit and returns. The specification calls that Svade, and Linux expects either.
- **Making a misaligned access.** A load or a store of a word at an address that is not a multiple of its size traps, with the address, and whoever is underneath makes the access a byte at a time: OpenSBI for a kernel that does not ask to do it itself.
- **The rest of the Advanced Interrupt Architecture's registers.** A hart reaches its IMSIC's two interrupt files, through `miselect`, `mireg` and `mtopei` for machine mode and `siselect`, `sireg` and `stopei` for supervisor mode. The others the architecture gives a hart (`mtopi`, `stopi` and the rest) are not there, and nothing run here has read one.
- **Cycle accuracy.** Every instruction takes the same time. Use it to find out what firmware does, not how many nanoseconds it takes.
- **Faster backends.** DBT-RISE can also translate blocks of RISC-V code into host code. socpuppet uses its interpreter.
- **Running on while another CPU is stopped.** SystemC runs every model in turn on one thread, and a CPU stopped in its debugger keeps it. So every other CPU stops with it, and simulated time stands still. That makes debugging several CPUs repeatable, and it is not how a board on a bench behaves. It also means a debugger is answered about memory only while its own CPU is the one stopped: with the host at a breakpoint, the SSD's GDB cannot read the SSD's memory until the host continues.

## Where it comes from

💡 This one is borrowed. The model is [DBT-RISE-RISCV](https://github.com/Minres/DBT-RISE-RISCV) by Minres, on their [DBT-RISE-Core](https://github.com/Minres/DBT-RISE-Core). socpuppet wraps it in a small adapter (`src/socpuppet/models/dbt_rise_cpu.cpp`) that joins its two bus sockets (one for fetching instructions, one for data) into one, gives it its clock, and exposes the three inputs.

Why this one, and what else was tried, is in the [ISS spike report](../iss-spike.md).

### Reading it

⚠️ Most of DBT-RISE's CPU is generated code, which is not written to be read from top to bottom. If you want to see how an instruction is executed:

- The instructions are described in a language called CoreDSL, and `src/vm/interp/vm_rv64imac.cpp` is generated from that description: a table of bit patterns, then one `case` per instruction. Pick one, such as `ADDI`, and read its case: decode the fields, compute, write the register. The host's core is `vm_rv64gc.cpp`, the same with floating point.
- What happens around the instructions is hand-written C++ in `src/iss/arch/riscv_hart_m_p.h`, or `riscv_hart_msu_vp.h` for the core with supervisor mode, and `riscv_hart_common.h`: how a trap is taken, what the control registers do, how an interrupt is noticed.
- Paging is `src/iss/mem/mmu.h`, which is short: `virt2phys` is the walk of the tables, one level each time round its loop.
- How the core sits in a SystemC simulation is `src/sysc/core_complex.cpp`: where time is kept, how memory is reached, where DMI comes in.

### What we changed

socpuppet holds the CPU to the same contract as the scripted stand-in (`tests/cpp/contracts/bus_master_contract.h`) and to tests of its own (`tests/cpp/platform/cpu_test.cpp`), and Zephyr's own suites run on it under twister. Every change is a patch in `cmake/patches/`, written up in [upstream.md](../upstream.md) with how to see what it mends. They come in four kinds:

- **For compilers and build systems**: four, none of which changes what the core does.
- **For the debugger**: a GDB server for each core where there was one for the process, each core's own `sysc` command on its own server, a `continue` that is answered once, and a debugger that hangs up rudely no longer ending the process.
- **What Zephyr and the contract found**: a reset raised a second time stopped the simulation, as did one shorter than a busy core's lead; a withdrawn DMI grant was ignored; an interrupt handler was entered over and over; a core with supervisor mode could never take a supervisor's interrupt, and dropped the instruction an interrupt arrived at; and firmware could clear a pending interrupt's bit that a real hart keeps read-only.
- **What running the hart the way Linux will run it found** (M22), where nothing had run it that way before: an instruction was fetched from its virtual address as if that were a physical one, so no kernel linked at a high address could have started; an interrupt that was pending at a system call was taken inside the call's handler; the status register hid the floating-point state from the kernel, and nothing marked it dirty; a store-conditional to another address left a reservation standing, which is the instruction Linux clears one with; user mode could execute `sret`; the counter-enable registers did nothing; and a dozen smaller things beside.

💡 None of that is a complaint. A model is trusted as far as it has been run, and this one had been run in machine mode. The page for sending the fixes back is [upstream.md](../upstream.md).
