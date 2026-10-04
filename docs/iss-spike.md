# The ISS spike: which CPU model goes in the CPU slot?

This is the report for milestone M1 in [plan.md](plan.md). It ends with a recommendation and a decision for Chris to make. Nothing that depends on the answer has been built.

**In one paragraph.** Four CPU models boot stock Zephyr `hello_world` for RV64 and RV32 behind socpuppet's draft CPU slot: DBT-RISE-RISCV, QBox, riscv-vp, and a thousand-line prototype of our own. A fifth, riscv-vp-plusplus, does not compile on macOS. QBox is the fastest by a factor of ten or more and is QEMU underneath, which is GPL. Among the ones that can ship in the wheel, the recommendation is a core of our own, with DBT-RISE-RISCV as the alternative if a working GDB server and a complete instruction set on day one matter more than a core a learner can read.

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

Every candidate was put through the same steps, in order, behind the same draft CPU slot (`spikes/iss/cpu_slot.h`): one bus socket, an interrupt input and a reset input, which is the shape the scripted bus master already has. The runnable steps are one test suite (`spikes/iss/harness/candidate_suite.h`) that each candidate's test program includes.

| Step | What is checked |
|---|---|
| S0 Read | License of everything linked or loaded, activity, instruction sets, reset, global state, GDB, macOS |
| S1 Build | Pinned by commit, against SystemC 3.0.2, as C++20, static where the candidate allows |
| S2 Link | One kernel in the process, with an RV64 and an RV32 instance side by side |
| S3 Smoke | A hand-encoded program prints `OK`, takes a trap and returns from it. Reset is held, released, raised again and released again |
| S4 Zephyr | Stock `hello_world` for `qemu_riscv64` and `qemu_riscv32` |
| S5 DMI | A probe in front of the RAM counts what still goes over the bus |
| S6 Speed | Instructions per second on a counted loop, with DMI on and off |
| S7 GDB | By reading, and one attach by hand where there is a server to attach to |
| S8 Glue | Lines of wrapper code and patches |

💡 Stock `hello_world` proves less than it looks. Its console driver polls the UART, and although the timer is set up, nothing needs an interrupt to arrive. The smoke program in S3 is there to catch a CPU whose traps or reset are broken and which would still print a greeting.

The stage the candidates perform on is in `spikes/iss/harness/`: socpuppet's own `Platform`, router and `Memory`, laid out at the addresses of QEMU's RISC-V `virt` machine, with 🎭 a stand-in UART that is always ready and keeps what is written to it. Zephyr's `qemu_riscv64` and `qemu_riscv32` boards are built for that memory map, so stock images run without a board of our own. The interrupt controller and the timer are plain memories that soak up writes.

**The box.** The spike was boxed by scope, not by the clock. A candidate stops at the first step that needs more than its allowance of source patches (about 20 lines each) or attempts. The two leads, DBT-RISE-RISCV and QBox, got 4 patches and 6 attempts a step. The others got 2 and 3. Adjusting the build from our side (a different library pin, a compiler flag, leaving a file out) is not a patch, but each adjustment is written down below.

## Results at a glance

| | DBT-RISE-RISCV | QBox | riscv-vp | In-house prototype |
|---|---|---|---|---|
| License | BSD-3-Clause | BSD-3 glue over GPL-2.0 QEMU | MIT | ours (MIT) |
| Builds as C++20 against SystemC 3.0.2 | ✅ | ✅ on its own SystemC, in its own tree | ✅ | ✅ |
| Lives in socpuppet's build | ✅ | ❌ a build of its own | ✅ | ✅ |
| macOS | ✅ | not tried | ✅ | ✅ |
| RV64 and RV32 in one simulation | ✅ | ✅ | ✅ | ✅ |
| Smoke program (print, trap, return) | ✅ | ✅ | ✅ | ✅ |
| Reset: hold, release, raise again | ✅ with a patch | ✅ | ✅ done by the wrapper | ✅ |
| Zephyr `hello_world`, RV64 and RV32 | ✅ ✅ | ✅ ✅ | ✅ ✅ | ✅ ✅ |
| DMI | ✅ | ✅ | ✅ but ignores invalidation | ✅ |
| Speed with DMI (million instructions a second) | 31 to 44 | 455 | 118 to 127 | 165 to 195 |
| GDB | ✅ attached and stepped | QEMU's stub, not tried | has one, does not build here | ❌ none |
| Source patches | 4 (2 on Linux) | 2 | 2 | none |
| New dependencies | 18 Boost libraries, ELFIO, SoftFloat | QEMU and about a dozen system packages | 3 header-only Boost libraries, SoftFloat | none |
| Can a learner read the core? | Generated code | No: QEMU's translator | Yes: one hand-written `switch` | Yes: written to be read |
| Validated beyond this spike? | Yes, upstream | Yes: it is QEMU | Yes, upstream | ❌ No |

riscv-vp-plusplus has no column: it stopped at the build step on macOS.

## The candidates

### DBT-RISE-RISCV (lead)

[DBT-RISE-RISCV](https://github.com/Minres/DBT-RISE-RISCV) is Minres's RISC-V ISS. It is built on SCC, the same Minres library socpuppet already uses for its router and logging. Tried at commit `2ad3223` (2026-09-24), with DBT-RISE-Core at `29e97c0`.

**Outcome: it passed every step, with four small source patches (two of them only needed by Clang).**

What it is:

- **License.** BSD-3-Clause, as are DBT-RISE-Core and its vector helpers. It links Berkeley SoftFloat (BSD-3-Clause), ELFIO (MIT) and Boost. Its TinyCC backend is LGPL and was left out.
- **Instruction sets.** RV32 and RV64, each as I, IMAC and GC, in machine-only, machine-and-user and full supervisor variants, with or without physical memory protection. The spike used `rv64imac_mp` and `rv32imac_mp`: machine mode with PMP, which Zephyr's QEMU boards switch on.
- **Backends.** An interpreter, and three translating backends (asmjit, LLVM, TinyCC) that turn blocks of guest code into host code. Only the interpreter was built. Each of the others is one more dependency, and would be faster than the figures here.
- **SystemC wrapper.** It comes with one, `sysc::riscv::core_complex`: TLM sockets, a reset input, interrupt inputs, real TLM DMI that waits for the DMI-allowed hint, SCC's quantum keeper, and a GDB server on a port you choose. No wrapper of the core had to be written, only a 100-line adapter around its outside.
- **Activity.** Last commit ten days before it was tried.

What it took to build (S1):

- Its own `CMakeLists.txt` was used, through `FetchContent`, with the three translating backends and the vector cores switched off.
- It builds as C++20 against SystemC 3.0.2 and against our pin of SCC, which is newer than the one it pins. No C++17 fallback was needed.
- ⚠️ It asks for a lot of Boost: coroutines for the interpreter, asio and threads for the GDB server, spirit for the debugger's command parser, serialization. socpuppet named two Boost libraries before; this names eighteen more, several of them compiled.
- ⚠️ Some of its sources need over a gigabyte of memory each to compile. Ten at once ran an 8 GB machine out of memory.
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
- **Reset.** Held high from the start and then released, it works as written. ⚠️ Raised a second time, it did not: the wrapper's run loop treats any interruption as "finished" and stops the whole simulation, a core asleep in `wfi` does not notice reset at all, and after a reset the time-keeping compares against a stale cycle count and stalls. A five-line patch to the wrapper fixes all three. This would otherwise have surfaced in M10, in the scenarios that reset a running die.
- **S4.** Stock Zephyr 4.4.2 `hello_world` printed its greeting on `qemu_riscv64` and on `qemu_riscv32`, unmodified, PMP and all.
- **S5.** A loop of 131,072 instructions made one bus transaction to RAM. Everything after the first fetch went through DMI.
- **S7.** ✅ With a port set, the core waits for a debugger. The Zephyr SDK's `gdb` connected, stopped at a breakpoint on `main`, showed a backtrace and the disassembly, single-stepped, and continued to the greeting.
- **Determinism.** It runs on the SystemC thread and nowhere else, and repeated runs finish at the same simulated time.
- **Time.** One instruction is one clock period, and the clock period is a signal the platform drives.

What a learner would read:

- The interpreter is generated, from a description of the instruction set in a language called CoreDSL. `vm_rv64imac.cpp` is 4,365 lines: a table of bit patterns, then one `case` per instruction. Each case is legible on its own (decode the fields, compute, write the register), but the file is not written to be read from top to bottom, and the source of truth is the CoreDSL, one step removed.
- The privilege and trap logic is hand-written C++ (`riscv_hart_m_p.h`, 526 lines, on a 1,100-line common base) and is where a learner would look for how a trap is taken.

### QBox (lead)

[QBox](https://github.com/qualcomm/qbox) is Qualcomm's library for putting QEMU's CPUs and devices inside a SystemC simulation. Tried at commit `b745c62` (2026-09-30), with its QEMU fork at `libqemu-v11.0.50-v0.1`. All of this was done in an Ubuntu 24.04 container (`spikes/iss/qbox/`). Nothing was installed on the Mac.

**Outcome: it passed every step behind socpuppet's CPU slot, and it is an order of magnitude faster than anything else here. It cannot be part of socpuppet's own build, and its CPU is GPL.**

What it is:

- **The CPU is QEMU.** 🎓 QEMU does not interpret. It translates blocks of guest instructions into host instructions and runs those, which is where the speed comes from. QBox builds QEMU as one shared library per target and loads it into the SystemC process.
- **License.** QBox's own code is BSD-3-Clause. QEMU is GPL-2.0 as a whole, and QBox's C++ wrapper is written against a GPL header. Its UART, interrupt controller, PCIe host and NVMe device are QEMU's device models, so they are GPL too.
- **Instruction sets.** Whatever QEMU's RISC-V target has, which is everything, including what the M3b MSI-X question turns on (AIA).
- **Activity.** A release the day before it was tried.

Standalone first (its own build system, its own platform described in Lua):

- It built with its own preset in 9 minutes 50 seconds at four jobs, for the two RISC-V targets only. The build tree is 2.6 GB. It wants about a dozen system packages (`spikes/iss/qbox/Dockerfile`).
- Stock Zephyr `hello_world` booted on `qemu_riscv64` and `qemu_riscv32`, and both booted in one process, each on a QEMU instance of its own (`both.lua`). That is the mixed-word-size case, by design: one library per word size.

Then behind the CPU slot (`spikes/iss/qbox/integration/`), which is where the build collisions the reading predicted had to be met:

- **C++17.** QBox builds as C++17, socpuppet is C++20, and SystemC refuses to link code built to different standards. So QBox was rebuilt as C++20, which took two source patches: QBox has a header called `semaphore.h`, which C++20's `<thread>` picks up in place of the C library's; and two constructors are spelled `Name<T>(...)`, which C++20 no longer allows. One component for another architecture (Hexagon) still fails as C++20 and was left unbuilt.
- **Its own SystemC, shared.** It forces shared libraries and pins a SystemC commit newer than the 3.0.2 release. socpuppet's platform layer is header-only, so it was compiled against QBox's SystemC in a tree of QBox's.
- **No SCC in the same program.** QBox brings its own copies of CCI and SCP, two libraries SCC bundles. socpuppet's router is SCC's, so the harness got a small router of its own for this one candidate (`simple_router.h`).
- **A sleeping CPU stops the clock.** ⚠️ A QBox CPU with nothing to do waits for an event from the host, and has the kernel wait with it: simulated time stops, and a run for a fixed length of time never returns. `Platform.run()` "until nothing is left to do" would not return either. The wrapper keeps a timed tick going so that time moves. Its own source says of this, "the SystemC kernel will never starve".

With those met, the same suite the others ran passed in full: both word sizes in one simulation, the smoke program, reset in all three phases through QBox's own reset input, both Zephyr boots, and DMI into socpuppet's own `Memory` (one bus transaction for 131,072 instructions). The wrapper is 125 lines.

Not established:

- **Time.** QBox was run in its deterministic configuration (QEMU as a coroutine on the SystemC thread, counting instructions for time). In its default, threaded configuration it is nine times faster again and makes no promise of repeatability. The spike did not verify that two deterministic runs are identical, and the simulated time at which the counted loop finished did not match one instruction per nanosecond as configured.
- **macOS.** QBox's CI builds on macOS for other targets. RISC-V on macOS was not tried.
- **Without DMI it crawls**: every instruction fetch becomes a round trip out of QEMU. That only matters if a CPU's path to RAM is traced.

What a learner would read: the boundary between QEMU and SystemC, which is instructive, and nothing of the CPU itself.

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

What it leaves you holding:

- Its GDB stub and its ELF loader were not built. Both use Linux-only headers, and the stub needs a parser library from a git submodule.
- ⚠️ Its RV64 instruction fetch reads a 32-bit value from an address that is only 2-byte aligned, which is undefined behaviour in C++. It works on the machines tried. A build with the undefined-behaviour sanitizer, which socpuppet's CI uses for its own tests, stops on it (`core/rv64/mem.h`, line 23).

### The in-house prototype (supporting)

`spikes/iss/inhouse/`: a hart written for the spike, to find out how much work a core of our own is.

**Outcome: it passed every step, in about a thousand lines, with no dependencies and no patches to carry.**

What it is:

- `hart.h`, 820 lines: registers, the fetch-decode-execute loop, traps, interrupts and the control and status registers, for RV32 and RV64 from one template. `compressed.h`, 210 lines: each 16-bit compressed instruction expanded into the 32-bit one it stands for.
- Plain C++ with no simulator in it, which is the shape socpuppet already asks of its models: the logic in a class that can be tested without the kernel, and a thin SystemC wrapper around it. The wrapper is 175 lines.
- I, M, A and C, machine mode only. That is exactly what the two Zephyr images are compiled for: 88 distinct instructions in the 64-bit image and 71 in the 32-bit one.

What it did: everything the others did. It booted both Zephyr images the first time it was run. Its DMI waits for the hint and gives the pointer back when the target says so. It was also the fastest of the interpreters on the counted loop, which says more about how little it does per instruction than about craft.

What it does not do, and would have to before M3 is over:

- ⚠️ **It is not validated.** Two programs and a boot are not a test suite. The official `riscv-tests` (BSD-3-Clause) are bare-metal programs that report pass or fail and would run on this harness as they are. Until it passes them, a firmware bug and a CPU bug look the same.
- **PMP is stored, not enforced.** Zephyr writes the registers and reads them back; nothing checks an access against them.
- **No GDB stub.** DBT-RISE-RISCV has one that works, QEMU has one, riscv-vp has one that does not build here. Ours would have to be written: the hart already executes one instruction at a time and exposes its registers, which is most of what a stub asks of a core.
- **No floating point, no supervisor or user mode.** Nothing in the plan needs them: every firmware is Zephyr in machine mode, and the handoff rules Linux out.

### Looked at, not built

- **Spike** (riscv-isa-sim, BSD-3-Clause): the RISC-V reference simulator. It is usable as a library, but it builds with autotools, has no GDB stub (it speaks to OpenOCD), and brings no SystemC. Its best use here would be as the reference to check a core of ours against.
- **TGC-ISS** (Minres): older packaging of the same cores DBT-RISE-RISCV contains.
- **libriscv, rv32emu, mini-rv32ima, dromajo**: a userspace sandbox, two RV32-only emulators, and an RV64-only one that is no longer maintained.

## Measurements

The loop is two instructions long (`addi`, `bne`) and runs 16.8 million times with DMI on and 1 million times with it off. The quantum was 1 ms of simulated time. Optimized builds with debug info. Figures are millions of instructions per second of real time, RV64 then RV32.

| Candidate | macOS, Apple clang | | Linux arm64, GCC 13 | |
|---|---|---|---|---|
| | DMI on | DMI off | DMI on | DMI off |
| DBT-RISE-RISCV (interpreter) | 44, 44 | 11, 11 | 37, 31 | 11, 11 |
| riscv-vp | 122, 127 | 17, 16 | 118, 121 | 19, 17 |
| In-house prototype | 166, 166 | 21, 22 | 193, 195 | 22, 23 |
| QBox behind the slot, deterministic | not tried | | 455, 460 | 0.4, 0.4 |

QBox on its own, on a loop of 2.1 billion instructions, in the same Linux container:

| Configuration | RV64 | RV32 |
|---|---|---|
| Deterministic (coroutine, instruction counting) | 414 M/s | 415 M/s |
| Threaded, unconstrained | 3,800 M/s | 3,800 M/s |

Both machines are the same Apple silicon laptop: Linux is Ubuntu 24.04 in a container on it. The CI job prints the same figures for GitHub's x86-64 runner in its log.

⚠️ A two-instruction loop flatters a simple interpreter and tells you little about real firmware. Read the table as "all three interpreters are in the same class, and QEMU is in another".

💡 For scale: Zephyr `hello_world` prints after about 70,000 instructions. At these speeds the boot is over before the test harness has finished clearing its throat.

## QBox and the license question

This is not legal advice. It sets out which licenses apply to what, and which judgements are Chris's.

The facts:

- QBox's glue is BSD-3-Clause. QEMU as a whole is GPL-2.0. QBox's wrapper is written against a GPL-2.0-or-later header, and QEMU is only available to it as a shared library.
- SystemC and SCC are Apache-2.0. The FSF and the ASF both hold that Apache-2.0 is not compatible with GPL version 2.
- The handoff's decision is that GPL code stays out of the core, and socpuppet's wheel is static and self-contained.

Three ways QBox could be part of socpuppet, and what follows from each:

| Arrangement | What follows | Is "GPL stays out of the core" still true? |
|---|---|---|
| In the main wheel | The wheel distributes GPL binaries in one process with Apache-2.0 SystemC, with source-offer duties, and stops being static and self-contained. | No |
| A separate optional package that the core loads through the registry | The MIT core contains no GPL code. The plug-in package is a GPL distribution that also links SystemC, and SystemC would have to be shared between the two. | Yes for the core. You take on the plug-in's distribution. |
| Source-only: a recipe and glue in the repo, built by users who opt in | The repo holds MIT glue. You distribute no QEMU code or binaries. This is how QBox itself ships. | Yes, most clearly |

The judgements that are yours: whether a plug-in that shares data structures in one process is a derived work; whether you are comfortable distributing anything that combines GPLv2 QEMU with Apache-2.0 SystemC; and whether MIT glue written against a GPL header belongs in the repo at all. The spike's QBox glue is in the repo now, under `spikes/iss/qbox/`.

What the spike adds to that picture is practical, not legal: QBox cannot be built inside socpuppet's build in any case. It needs its own SystemC, shared libraries, a C++20 rebuild with patches, and a dozen system packages. So the only arrangements that were ever on the table are the second and third, and the third is the one that was actually exercised.

## VCML or a thin layer of our own?

[VCML](https://github.com/machineware-gmbh/vcml) (MachineWare, Apache-2.0) is a library of TLM models and the infrastructure under them: registers, properties, its own socket types, and models of UARTs, interrupt controllers, timers and PCI. It has no RISC-V ISS, so it was never a candidate for the CPU slot. The probe asked two things.

**Does it build here?** ✅ Yes, cleanly. Release `v2026.10.02` builds against this tree's SystemC 3.0.2 as C++20, on macOS and Linux, with no patches and everything optional switched off. Three things to know:

- ⚠️ It fetches its support library, mwr, by cloning the head of its default branch while CMake configures. There is no pin to set from outside, so two builds a week apart can differ.
- It defines `SC_DISABLE_API_VERSION_CHECK` for everything that links it, which switches off the SystemC check that catches mixed C++ standards.
- It is about 80,000 lines.

**Can one of its models stand in a socpuppet platform?** ✅ Yes. `spikes/iss/vcml_probe/` puts VCML's 16550 UART where the stand-in UART was, under the in-house CPU, and Zephyr's own driver prints its greeting through it. The adapter is about fifty lines: VCML's socket hands out a plain TLM socket on request, and its clock, reset, interrupt and receive ports each need something bound to them.

**Recommendation: a thin layer of our own, with VCML as a library to borrow from one model at a time.**

- socpuppet's models are meant to be read, and each has a page saying what it stands for and what it leaves out. A VCML model brings VCML's world with it: its own sockets, registers and property system. A learner opening it meets the framework before the hardware.
- The cost of our own layer so far is small: `Memory` is under 70 lines.
- The probe shows the door stays open. If a model turns out to be too large to write, PCIe in M2 being the likely first, VCML's can be put behind a fifty-line adapter without the rest of the platform knowing. That decision can be made model by model, with this recipe.

## Which Zephyr to pin

**Recommendation: 4.4.2 with SDK 1.0.1, which is what the spike used, moving to the next LTS when it lands.**

- 4.4 is the current stable release. The current LTS is 3.7, and the next is planned for 4.6. M3b's question about MSI-X on RISC-V depends on recent interrupt-controller support, which argues against pinning the old LTS.
- The minimal SDK with only the RISC-V toolchain is about 225 MB to download, and one toolchain builds for both word sizes. `spikes/iss/firmware/build.sh` fetches it and builds both images in about two minutes from nothing, and in seconds after that.
- ⚠️ Zephyr 4.4.2 does not configure outside a west workspace. (🎓 west is Zephyr's tool for managing the set of repositories it is built from.) Building with plain CMake fails on a file that only the west path generates. The script works around it by making its directory a workspace with Zephyr as the only repository.
- The stock QEMU boards compile `hello_world` as `rv64imac_zicsr_zifencei` and `rv32imac_zicsr_zifencei`, with PMP on.

## Recommendation

**The default CPU: a core of our own, built test-first in M3a.** The spike's prototype is the sketch for it, not the thing itself.

Why, against the criteria:

- **It is the only one a learner can read end to end**, and the handoff puts that first. The others are generated code, QEMU's translator, or a textbook interpreter that is no longer developed.
- **It adds nothing to the build.** DBT-RISE-RISCV adds eighteen Boost libraries and four patches to carry. riscv-vp adds two patches and undefined behaviour our sanitizer job would stop on. A core of ours builds wherever socpuppet builds, and the wheel stays as small as it is.
- **It already has the shape socpuppet asks for**: plain C++ that can be tested without the kernel, behind a thin wrapper.
- **Zephyr asks little of a CPU.** About ninety distinct instructions, machine mode, a handful of control registers. The prototype met that in a thousand lines and was not slower than the alternatives.

What it costs, plainly:

- Every CPU bug is ours. The mitigation is the `riscv-tests` suite in CI from the first day of M3a, before any firmware is debugged on it.
- A GDB stub has to be written. It is on M3a's list already.
- If a later milestone needs floating point, supervisor mode or an MMU, that is ours to write as well. Nothing in the plan does.

**If you would rather not own a CPU: DBT-RISE-RISCV.** It is the strongest of the ready-made cores that can ship in the wheel. It has a GDB server that works today, the complete instruction set, faster backends to turn on later, and it comes from the people who wrote the router socpuppet already uses. The price is the dependencies, the patches (two would go upstream as fixes for Clang, one is a real bug in reset), and a core a learner cannot follow.

**QBox: not the default, and worth keeping as an optional fast tier that users build from source.** It does everything, ten times faster, and the spike has it working behind the slot in 125 lines. It cannot live in the wheel for licence reasons and cannot live in the build for practical ones. Nothing in M3 to M5 needs its speed: a boot is tens of thousands of instructions. The time to build the tier is when a firmware team wants to run something long, and the recipe in `spikes/iss/qbox/` is the starting point.

**riscv-vp: no.** It works, but it is the unmaintained ancestor of a fork that does not build on macOS. A core of our own has its virtues without its baggage.

The CPU slot makes this less of a one-way door than it sounds. All four sat behind the same three ports and passed the same suite. Whichever is chosen, the suite becomes the slot's contract, and a second implementation can be added later without its neighbours knowing.

## What M3a inherits

- **The DMI hint.** `Memory` now sets it and the tracer withholds it. Both were changed test-first before the spike, because every candidate that uses real TLM DMI waits for the hint.
- **The quantum.** Nothing in socpuppet sets the global quantum, and left at zero every instruction is a hand-over to the kernel. The spike's harness sets it. `Platform` needs a way to, from Python.
- **The CPU slot.** A draft is in `spikes/iss/cpu_slot.h`. The real one belongs in `src/socpuppet/platform/slots.h`, and `candidate_suite.h` is the first draft of its contract suite: two word sizes together, a trap, reset in three phases, a boot, DMI.
- **Reset for free.** `async_reset_signal_is` on the CPU's thread gives hold, release and restart without the core's help.
- **Loading an image.** A flat binary written through the existing debug transport is all the spike needed. `_core.debug_write` already takes bytes of any length; only the Python `poke32` is narrow. ELF parsing can stay in Python.
- **What a real boot will need that `hello_world` did not**: a timer that fires and an interrupt controller that delivers. Zephyr's `synchronization` sample, M3a's second exit test, depends on both.
- **Devicetree.** The generator knows only `Memory`. CPU nodes need an `riscv,isa-extensions` property for Zephyr 4.4.
- **Sleep and `Platform.run()`.** With the three interpreters, a platform whose CPU is asleep in `wfi` has nothing left to do, and `run()` returns. The suite checks that, and it belongs in the contract. QBox is the exception.
- **If DBT-RISE-RISCV is chosen instead**: the Boost list in `spikes/iss/boost_libraries.cmake`, the patches in `spikes/iss/patches/`, and a static build of its core for the wheel.

## Not exercised

- **Python.** The candidates ran under C++ tests only. Putting one in the Python extension touches the wheel, and that is M3's work.
- **An interrupt arriving.** No test raised the interrupt line.
- **Three CPUs.** Two ran together, one of each word size. The full platform has three.
- **x86-64 Linux, except in CI.** The local Linux runs were arm64.
- **QBox on macOS**, QBox's GDB stub, and whether its deterministic mode repeats exactly.
- **DBT-RISE-RISCV's translating backends**, which are its answer on speed.
- **Real workloads.** The speed figures are for a two-instruction loop.
- **`riscv-tests`**, on any candidate.

## Decision needed

1. **The default CPU for M3a**: a core of our own (recommended), or DBT-RISE-RISCV.
2. **QBox**: keep the recipe as the start of an optional, source-built fast tier (recommended), build that tier now, or drop it. If it stays in any form, which of the licence arrangements above you are comfortable with.
3. **Modeling library**: a thin layer of our own, borrowing VCML models one at a time behind an adapter (recommended), or building on VCML.
4. **Zephyr**: pin 4.4.2 with SDK 1.0.1 (recommended).

Until then `spikes/iss/` stays as it is, with every candidate in place and running in CI, so that the choice can still go any way. Once the choice is made, the candidates that were not chosen are deleted, and the chosen one's code goes when M3a has rebuilt it test-first and passed the same boot.
