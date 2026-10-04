# The ISS spike: which CPU model goes in the CPU slot?

🚧 **In progress.** This is the report for milestone M1 in [plan.md](plan.md). It is filled in as each candidate is tried. Sections marked 🚧 are still to come, and there is no recommendation yet.

## The question

socpuppet has no CPU yet. From M3 on, three firmware images (one RV64 host, two RV32 controllers) have to run inside one simulation, each on a model of a RISC-V processor.

🎓 That model is an ISS, an instruction-set simulator: a program that does what the processor would do, one instruction after another. It fetches an instruction from memory, works out what it means, changes the registers and memory accordingly, and moves on. Everything else in a virtual platform exists to be read and written by it.

Several open ISSs exist, and writing our own is possible too. This spike tries the candidates out against one checklist before anything is built on top of one. It also settles two smaller questions that hang off the same evidence: whether to build on a modeling library such as VCML, and which Zephyr release to pin.

## What a candidate is judged on

The criteria come from the [handoff](handoff-socpuppet.md), with three added that reading the candidates showed to matter.

| Criterion | Why it matters here |
|---|---|
| In-process | One SystemC kernel runs every die and the SSD, so the CPU model has to live inside that process. |
| Loosely timed, with DMI | 🎓 DMI (direct memory interface) hands the CPU a pointer to the RAM, so that fetching an instruction is a memory read and not a bus transaction. It is what makes a boot take seconds. |
| Boots Zephyr | The firmware is Zephyr, for RV64 and for RV32IMAC. |
| License | socpuppet is MIT and ships as a self-contained wheel. The handoff keeps GPL code out of the core. |
| C++20 | Preferred, not required. SystemC bakes the C++ standard into a link-time check, so everything linking it must agree. |
| Build simplicity | It has to build from source under our CMake, on Ubuntu 24.04 and macOS, with nothing installed on the machine. |
| Mixed word sizes (added) | An RV64 core and RV32 cores have to coexist in one process. |
| Reset (added) | The IO-die manager holds the compute die in reset and then releases it, and later scenarios reset a die that is already running. |
| Can a learner read it? (added) | socpuppet is a learning tool first. The handoff puts readability ahead of speed. |

## How each candidate was tried

Every candidate that got a build was put through the same steps, in order, behind the same draft CPU slot (`spikes/iss/cpu_slot.h`): one bus socket, an interrupt input and a reset input, which is the shape the scripted bus master already has.

| Step | What is checked |
|---|---|
| S0 Read | License of everything linked or loaded, activity, instruction sets, reset, global state, GDB, macOS |
| S1 Build | Pinned by commit, against SystemC 3.0.2, as C++20, static where the candidate allows |
| S2 Link | One kernel in the process, with an RV64 and an RV32 instance side by side |
| S3 Smoke | A hand-encoded program prints `OK`, takes a trap and returns from it. Reset is held, released, raised again and released again |
| S4 Zephyr | Stock `hello_world` for `qemu_riscv64` and `qemu_riscv32` |
| S5 DMI | A probe in front of the RAM counts what still goes over the bus |
| S6 Speed | Instructions per second on a counted loop, with DMI on and off |
| S7 GDB | By reading; one manual attach for the finalist |
| S8 Glue | Lines of wrapper code, CMake and patches |

💡 Stock `hello_world` proves less than it looks. Its console driver polls the UART, and although the timer is set up, nothing needs an interrupt to arrive. The smoke program in S3 is there to catch a CPU whose traps or reset are broken and which would still print a greeting.

The stage the candidates perform on is in `spikes/iss/harness/`: socpuppet's own `Platform`, router and `Memory`, laid out at the addresses of QEMU's RISC-V `virt` machine, with 🎭 a stand-in UART that is always ready and keeps what is written to it. Zephyr's `qemu_riscv64` and `qemu_riscv32` boards are built for that memory map, so stock images run without a board of our own. The interrupt controller and the timer are plain memories that soak up writes.

**The box.** The spike is boxed by scope, not by the clock. A candidate stops at the first step that needs more than its allowance of source patches (about 20 lines each) or attempts. The two leads, DBT-RISE-RISCV and QBox, get 4 patches and 6 attempts a step. The others get 2 and 3. Adjusting the build from our side (a different library pin, a compiler flag, leaving a file out) is not a patch, but each adjustment is written down. A candidate that fails only on C++20 may be retried as C++17, inside the spike build only.

## Results at a glance

🚧 Filled in as candidates are tried.

| | DBT-RISE-RISCV | QBox | riscv-vp-plusplus | In-house |
|---|---|---|---|---|
| License | BSD-3-Clause | 🚧 | 🚧 | 🚧 |
| Builds as C++20, static, SystemC 3.0.2 | ✅ with patches (below) | 🚧 | 🚧 | 🚧 |
| RV64 and RV32 in one simulation | ✅ | 🚧 | 🚧 | 🚧 |
| Smoke program (print, trap, return) | ✅ | 🚧 | 🚧 | 🚧 |
| Reset: hold, release, raise again | ✅ with a patch | 🚧 | 🚧 | 🚧 |
| Zephyr `hello_world`, RV64 and RV32 | ✅ ✅ | 🚧 | 🚧 | 🚧 |
| DMI | ✅ | 🚧 | 🚧 | 🚧 |
| Speed, DMI on (million instructions a second) | 44 | 🚧 | 🚧 | 🚧 |
| Source patches | 4 (2 on Linux) | 🚧 | 🚧 | 🚧 |
| Glue (lines) | 220 | 🚧 | 🚧 | 🚧 |
| Can a learner read the core? | Generated code | 🚧 | 🚧 | 🚧 |

## The candidates

### DBT-RISE-RISCV (lead)

[DBT-RISE-RISCV](https://github.com/Minres/DBT-RISE-RISCV) is Minres's RISC-V ISS. It is built on SCC, the same Minres library socpuppet already uses for its router and logging. Tried at commit `2ad3223` (2026-09-24), with DBT-RISE-Core at `29e97c0`.

**Outcome: it passed every step, with four small source patches (two of them only needed by Clang).**

What it is:

- **License.** BSD-3-Clause, as are DBT-RISE-Core and its vector helpers. It links Berkeley SoftFloat (BSD-3-Clause), ELFIO (MIT) and Boost. Its TinyCC backend is LGPL and was left out.
- **Instruction sets.** RV32 and RV64, each as I, IMAC and GC, in machine-only, machine-and-user and full supervisor variants, with or without physical memory protection. The spike used `rv64imac_mp` and `rv32imac_mp`: machine mode with PMP, which Zephyr's QEMU boards switch on.
- **Backends.** An interpreter, and three translating backends (asmjit, LLVM, TinyCC) that turn blocks of guest code into host code. Only the interpreter was built. Each of the others is one more dependency.
- **SystemC wrapper.** It comes with one, `sysc::riscv::core_complex`: TLM sockets, a reset input, interrupt inputs, real TLM DMI that waits for the DMI-allowed hint, SCC's quantum keeper, and a GDB server on a port you choose. No wrapper of the core had to be written, only an adapter around its outside.
- **Activity.** Last commit eleven days before it was tried.

What it took to build (S1):

- Its own `CMakeLists.txt` was used, through `FetchContent`, with the three translating backends and the vector cores switched off.
- It builds as C++20 against SystemC 3.0.2 and against our pin of SCC, which is newer than the one it pins. No C++17 fallback was needed.
- ⚠️ It asks for a lot of Boost: coroutines for the interpreter, asio and threads for the GDB server, spirit for the debugger's command parser, serialization. socpuppet used two Boost libraries before; with this it uses eighteen.
- Its main library is declared `SHARED`. The SystemC part is static, so the kernel stays in one place, but a wheel would need the core static too.
- Four adjustments from our side, none of them to its source: naming each Boost library whose headers it includes (it assumes a system-wide Boost with one include directory); leaving one file out on macOS, where a helper for the translating backends declares a C function called `wait()` and collides with POSIX; one compiler flag for Clang; and linking the whole SystemC library, because the cores register themselves from a static initializer nothing refers to.

The four source patches (`spikes/iss/patches/`):

| Patch | Lines | Needed on | Why |
|---|---|---|---|
| asio names | 4 | everywhere | Boost 1.87 removed `io_service` and `io_context::work`. Our Boost is 1.89. |
| 128-bit integer traits | 3 | Clang's library only | It specializes a private template of GCC's standard library. |
| `offsetof` | one rule, 9 generated headers | Clang only | `offsetof(type, type::member)` is accepted by GCC and rejected by Clang. |
| Reset restarts the core | 5 | everywhere | See below. |

That is exactly the lead's allowance of four. On Linux with GCC only two are needed.

What it did:

- **S2, S3.** An RV64 and an RV32 core ran the smoke program side by side in one simulation, and both printed, trapped and returned.
- **Reset.** Held high from the start and then released, it works as written. ⚠️ Raised a second time, it did not: the wrapper's run loop treats any interruption as "finished" and stops the whole simulation, a core asleep in `wfi` does not notice reset at all, and after a reset the time-keeping compares against a stale cycle count and stalls. A five-line patch to the wrapper fixes all three. This would have surfaced in M10, in the scenarios that reset a running die.
- **S4.** Stock Zephyr 4.4.2 `hello_world` printed its greeting on `qemu_riscv64` and on `qemu_riscv32`, unmodified, PMP and all.
- **S5.** A loop of 131,072 instructions made one bus transaction to RAM. Everything after the first fetch went through DMI.
- **Determinism.** It runs on the SystemC thread and nowhere else, and repeated runs finish at the same simulated time.
- **Time.** One instruction is one clock period, and the clock period is a signal the platform drives.

What a learner would read:

- The interpreter is generated, from a description of the instruction set in a language called CoreDSL. `vm_rv64imac.cpp` is 4,365 lines: a table of bit patterns, then one `case` per instruction. Each case is legible on its own (decode the fields, compute, write the register), but the file is not written to be read from top to bottom, and the source of truth is the CoreDSL, one step removed.
- The privilege and trap logic is hand-written C++ (`riscv_hart_m_p.h`, 526 lines, on a 1,100-line common base) and is where a learner would look for how a trap is taken.

### riscv-vp-plusplus (stopped at the build step on macOS)

[riscv-vp-plusplus](https://github.com/ics-jku/riscv-vp-plusplus) is the active fork of riscv-vp, from JKU Linz: MIT, RV32 and RV64 up to GC with vectors, already on SystemC 3.0. Tried at commit `1dfbcb1` (2026-09-15).

**Outcome: ❌ its ISS does not compile on macOS, and what it would take is well past a patch.** It was not taken further, on either system.

- The fork's main addition is a faster core, and the speed comes from how it dispatches instructions: each instruction's handler is a label inside one huge function, and the table of labels is collected by the linker from a named ELF section. 🎓 ELF is the object-file format of Linux. macOS uses Mach-O, where sections are named differently and the trick of asking the linker for a section's start and end has another spelling. The first error, 35 times over: `argument to 'section' attribute is not valid for this target: mach-o section specifier requires a segment and section separated by a comma` (`core/rv64/iss_ctemplate.cpp`).
- Two smaller ones before it: `__always_inline` is a macro from Linux's C library that the core uses without defining (a compiler flag on our side fixed that), and a call to `sc_time`'s constructor that is ambiguous where `uint64_t` is not `unsigned long`.
- Its own source says that an RV32 and an RV64 core in one program "compile but give runtime errors", marked as a to-do.

macOS is a supported development host for socpuppet, so a core that builds only on Linux cannot be the default CPU. As the plan allowed, the original riscv-vp's simpler core took its place.

### riscv-vp (supporting)

[riscv-vp](https://github.com/agra-uni-bremen/riscv-vp) is the University of Bremen's original: MIT, RV32GC and RV64GC with machine, supervisor and user modes. Tried at commit `48b2f58` (2024-12-13, its latest).

**Outcome: it passed every step, with two small source patches.**

What it is:

- An ISS as a plain C++ object (`rv32::ISS`, `rv64::ISS`), and a second object that turns its memory accesses into TLM transactions. A platform's `main()` is expected to supply the rest. The interpreter is one hand-written `switch`, about 1,900 lines per word size, and reads like a textbook.
- Written for SystemC 2.3 and C++17, and last touched in December 2024. Development has moved to the fork.
- Only the two ISS sources, the instruction decoder and its copy of SoftFloat were compiled, from our own CMake. Its build brings a whole virtual platform and a SystemC of its own. It needs three header-only Boost libraries.

What it took:

| Patch | Lines | Why |
|---|---|---|
| Named-thread macro | 3 | It is written against the inside of SystemC 2.3. The fork has the SystemC 3.0 form. |
| Two global tables | 4 | The 32-bit and 64-bit ISS each define `regnames` and `regcolors`, so the two would not link into one program. |

Plus a 180-line wrapper, which supplies what a riscv-vp `main()` would:

- **The thread.** riscv-vp's own runner stops the simulation when the ISS returns.
- **Reset.** The ISS has no notion of it. The wrapper uses SystemC's own asynchronous reset of a thread (`async_reset_signal_is`): when the line goes high the kernel abandons whatever the thread was doing and starts it again, and the wrapper builds a fresh ISS. 💡 This needs nothing from the ISS, so it works for any ISS that runs on a thread we own.
- **DMI.** The ISS takes a raw pointer to RAM before it starts. The wrapper asks for one the TLM way first. ⚠️ The ISS keeps the pointer for good: a target that takes its DMI back is not obeyed.
- **A timer and a bus lock**, which the ISS expects to be handed.

What it did: RV64 and RV32 side by side, the smoke program, reset in all three phases, Zephyr `hello_world` on both boards, and no bus traffic to RAM at all once DMI was set up. It gives each instruction a time of its own (10 ns, more for loads, stores, multiplies and divides).

What it leaves you holding: its GDB stub and its ELF loader were not built. Both use Linux-only headers, and the stub needs a parser library from a git submodule.

### The in-house prototype (supporting)

`spikes/iss/inhouse/`: a hart written for the spike, to find out how much work a core of our own is.

**Outcome: it passed every step, in about a thousand lines, with no dependencies.**

What it is:

- `hart.h`, 820 lines: registers, the fetch-decode-execute loop, traps, interrupts and the control and status registers, for RV32 and RV64 from one template. `compressed.h`, 210 lines: each 16-bit compressed instruction expanded into the 32-bit one it stands for.
- Plain C++ with no simulator in it, which is the shape socpuppet already asks of its models: the logic in a class that can be tested without the kernel, and a thin SystemC wrapper around it. The wrapper is 175 lines.
- I, M, A and C, machine mode only. That is exactly what the two Zephyr images are compiled for: 88 distinct instructions in the 64-bit image and 71 in the 32-bit one.

What it did: everything the others did. It booted both Zephyr images the first time it was run. Its DMI waits for the hint and gives the pointer back when the target says so, which neither riscv-vp nor the QBox wrapper needed asking for and riscv-vp cannot do.

What it does not do, and would have to before M3 is over:

- ⚠️ **It is not validated.** Two programs and a boot are not a test suite. The official `riscv-tests` (BSD-3-Clause) are bare-metal programs that report pass or fail and would run on this harness as they are. Until it passes them, a firmware bug and a CPU bug look the same.
- **PMP is stored, not enforced.** Zephyr writes the registers and reads them back; nothing checks an access against them.
- **No GDB stub.** DBT-RISE-RISCV has one, QEMU has one, riscv-vp has one that does not build here.
- **No floating point, no supervisor or user mode.** Nothing in the plan needs them: every firmware is Zephyr in machine mode, and the handoff rules Linux out.

### QBox (lead)

🚧 Standalone results are in the measurements below. The integration behind the CPU slot is being run.

## Measurements

Apple M-series laptop, Apple clang, optimized build with debug info. The loop is two instructions long (`addi`, `bne`) and runs 16.8 million times with DMI on and 1 million times with it off. The quantum was 1 ms of simulated time.

| Candidate | Word size | DMI on | DMI off |
|---|---|---|---|
| DBT-RISE-RISCV (interpreter) | RV64 | 44 M instructions/s | 11 M/s |
| DBT-RISE-RISCV (interpreter) | RV32 | 45 M/s | 11 M/s |

🚧 The same on the CI runner, and the other candidates.

💡 For scale: Zephyr `hello_world` printed after about 70,000 instructions. At these speeds a boot is over before the test harness has finished starting.

## QBox and the license question

🚧 To come, with QBox's results.

## VCML or a thin layer of our own?

🚧 To come.

## Which Zephyr to pin

🚧 To come. The spike used 4.4.2, the current stable release, with SDK 1.0.1.

⚠️ One finding already: Zephyr 4.4.2 does not configure outside a west workspace. (🎓 west is Zephyr's tool for managing the set of repositories it is built from.) Building with plain CMake, which the Zephyr docs describe, fails on a file that only the west path generates. The firmware script works around it by making its directory a workspace with Zephyr as the only repository.

## Recommendation

🚧 To come.

## What M3a inherits

🚧 To come. Known so far:

- `Memory` now sets the DMI-allowed hint, and the tracer withholds it. Both changes were made test-first before the spike, because every candidate that uses real TLM DMI waits for the hint.
- Nothing in socpuppet sets the global quantum. The spike's harness does. `Platform` needs a way to.
- The CPU slot is a draft in `spikes/`. The real one belongs in `src/socpuppet/platform/slots.h`, with a contract suite.

## Not exercised

🚧 To come. Known so far:

- Python. The candidates ran under C++ tests only. Putting one in the Python extension touches the wheel, and that is M3's work.
- Interrupts arriving. No test raised the interrupt line.
- GDB.

## Decision needed

🚧 To come.
