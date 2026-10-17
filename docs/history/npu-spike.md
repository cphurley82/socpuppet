# The NPU spike: a Hexagon from QBox, or a behavioral NPU of our own?

This is the report of a time-boxed spike for milestone M12 in [roadmap.md](../roadmap.md). It ends with a recommendation and a stop: the decision is recorded at the end when it is made. The spike's code is in [spikes/npu](../../spikes/npu/README.md), behind the `spike` preset, and stays there until M19 has rebuilt what the decision keeps.

**In one paragraph.** 🎭 A behavioral NPU of our own is the one to build, on the compute die. It fits behind the draft accelerator slot as the DMA engine's shell around 200 lines of plain C++, takes the exit test's multiply from a descriptor in 12 ms, and comes in two flavours: the arithmetic in C++, and 🧵 the arithmetic handed to numpy through the Python executor, which is 50% slower and lets a user define the block's operation in Python. QBox's Hexagon also fits behind the slot, runs a C program compiled with stock clang, and does the same multiply in 1.5 s, which is a real programmable DSP doing real work and a hundred times the wait; but everything about it is a reason to keep it optional rather than central: it is QEMU underneath (GPL-2.0, never in the wheel, built in a container), its firmware side is a program somebody compiles with no open operating system to write it against, Linux's way of talking to it (FastRPC) has a closed half on the DSP, and its QBox pin was broken at the head of `main` the week this spike ran. The doorbell between host and accelerator is the same block either way, so a Hexagon can be put behind the slot later without the host's firmware noticing. The decision, made the same day, is under [Decisions](#decisions): the behavioral NPU, with its arithmetic in Python.

## The question

🎓 An NPU (neural processing unit) is the block an SoC hands its matrix arithmetic to. Firmware describes the work in memory (where the operands are, where the result goes, how big they are), tells the block where that description is through a register block, and is interrupted when the block is done. Behind the registers, real NPUs are one of two things: a fixed-function engine that does its arithmetic in hardware (a systolic array, say), or a programmable processor (a DSP) running a program that does the arithmetic. Qualcomm's NPUs are built on Hexagon, their DSP.

No open model was found that fits as it stands ([the three set aside](#what-was-set-aside-without-a-build)), so M12 is a spike in the shape of M1's and M2's: two candidates behind one slot, a report, and a stop for a decision.

- **QBox's Hexagon** (`qemu_cpu_hexagon`): a real programmable accelerator. The work is a program compiled for the core.
- 🎭 **A behavioral NPU of our own**: its registers, its descriptor in memory, its DMA and its interrupt are modelled, and the multiplying is done by the machine running the simulation, with nothing of a processor in it. Two flavours: plain C++, and numpy through the Python executor.

Both sit behind one draft slot (a bus master, a register block, an interrupt line) and share one block of ours, a doorbell, because a Hexagon core has an interrupt controller for what comes in and nothing that raises a line on somebody else.

## What was tried

Everything is in `spikes/npu/`. The behavioral candidate and the doorbell were built and run on macOS (x86-64, Apple clang 21) in socpuppet's own tree. The Hexagon candidate was built and run in a container (Ubuntu 24.04, GCC 13, clang 18) against QBox at `4d63017c` (2026-09-24) and its QEMU fork at `libqemu-v11.0-v0.15`.

- **The draft slot** (`accelerator_slot.h`): `socket`, a bus master through which the block reads the descriptor and its operands and writes its result; `cpu`, its register block; `irq`, one line towards the host. It is the DMA engine's shape with one memory in place of two, and both candidates `static_assert` against it.
- **The doorbell** (`doorbell.h`, `doorbell_module.h`): the three registers of a command device (`regs/command_device.rdl`), then the descriptor's address in two halves, and on a second face for the accelerator's own core, `PENDING` (what was asked) and `COMPLETE` (which the core writes when done). A test rings it with 🎭 a stand-in core and sees the host interrupted.
- **The descriptor**: 40 bytes in memory. `C = A × B`, A being m by k and B k by n, both 8-bit signed integers, C m by n of 32-bit ones, which is what real NPUs accumulate 8-bit products into.
- 🎭 **The behavioral NPU** (`behavioral/`): `NpuLogic` is the doorbell's logic plus "read the descriptor, read A and B, multiply, write C". It fits socpuppet's `CommandLogic` concept, so its SystemC shell is the DMA engine's `CommandDevice`, unchanged. The arithmetic is behind a `Multiplier` interface with two implementations. The numpy one runs through socpuppet's `PythonExecutor`, because the multiply is called from a SystemC thread and CPython may not be called from one of those; its test embeds an interpreter.
- **QBox's Hexagon** (`hexagon/`): the core with its global registers and TLB, on a bus of its own (the host's memory at the same addresses, 1 MiB of program memory, the doorbell's second face), behind the slot. The program (`firmware/matmul.c`, 80 lines of C) waits at the doorbell, multiplies, writes `COMPLETE`. It is compiled by Ubuntu's stock clang, whose Hexagon back end needs no toolchain of Qualcomm's, with no C library. QBox's own Hexagon tests are assembly only; this is a C program on a Hexagon in QBox, which is a step further than the tests go.
- **The exit test, three times over**: the host puts two 256 by 256 matrices and a descriptor in memory, rings the bell with the interrupt enabled, and the product is in memory and the line has risen. Each run prints how long the machine took.

## Answers

| # | Question | Behavioral, C++ | Behavioral, numpy | QBox Hexagon | How |
|---|---|---|---|---|---|
| 1 | Fits behind the slot, in-process? | ✅ One `CommandDevice`. | ✅ The same device with another `Multiplier`. | ✅ Core, registers, TLB, a router and the doorbell inside one module; QBox is in-process as it was for the ISS spike (a coroutine on the SystemC thread, instruction counting for time). | measured |
| 2 | Licence | MIT, ours. | MIT, plus numpy (BSD-3-Clause) at the user's side. | QBox BSD-3-Clause around QEMU GPL-2.0. Optional, built from source, never in the wheel. | read |
| 3 | What the build costs | Nothing new. | A Python library to embed in the test and numpy in a dependency group. The extension already embeds the executor. | A container, a 2.5 GB build tree, and the first build takes about eight minutes with eight jobs, QEMU included, plus a clone of each. macOS was not tried: QBox wants its own SystemC as a shared library. | measured |
| 4 | The firmware's side | A driver: five register writes and an interrupt handler. | The same driver. | The same driver on the host, plus a program on the DSP that somebody compiles and loads, with no C library and no operating system behind it. QuRT, the RTOS Hexagon firmware is normally written against, is closed. | measured, read |
| 5 | What Linux would need | One memory region and one interrupt, which `uio_pdrv_genirq` binds from the devicetree with `of_id=` and no kernel code. | The same. | FastRPC: `drivers/misc/fastrpc.c` is in mainline, the library is open (`quic/fastrpc`), and the half that runs on the DSP (the shell, QuRT) is closed. A UIO-style driver that talks to the doorbell is possible too, and then the DSP's program is the device's firmware. | read |
| 6 | Speed, 256 × 256 × 256 int8 | 11 to 14 ms. | 18 ms, numpy already imported (1.2 s with the import, once). | 1.5 s of wall-clock time, three runs within 2%. 🎓 That is QEMU translating and running about 17 million multiply-accumulates, one Hexagon instruction at a time; a real Hexagon would use its vector unit, which the program does not. | measured |
| 7 | The doorbell | Used through its host face only; `COMPLETE` is a call. | The same. | Both faces, as designed: the host rings, the core reads `PENDING` and the descriptor's address and writes `COMPLETE`, the host is interrupted. | measured |

Speeds are from a RelWithDebInfo build on one core of an x86-64 Mac, and each is the whole run, bus traffic included. ⚠️ They say what a model costs the person waiting for it, not what the hardware would take.

## What was found on the way

- **QBox's `main` could not be built.** Its lock file pins a libqemu tag that is not published, from 2026-10-05 on, and the ISS spike's recipe names a commit with the same problem. The spike built the commit before it. 📮 In [upstream.md](../upstream.md).
- **The planning worry about QEMU's Hexagon was misplaced.** Planning feared QBox pinned a QEMU older than the one that gained Hexagon system mode. QBox takes its QEMU from Qualcomm's own fork, and that fork has had a Hexagon machine (`hw/hexagon/`) all along; upstream QEMU gained it in 11.1 (2026-08) from the same source.
- **There is no Hexagon platform in QBox, and no C.** None of its platforms instantiates the core, and its Hexagon tests are hand-assembled. Everything about how to wire the core, what it needs around it (its global registers, a TLB), and where it starts (`hexagon_start_addr` on the global registers, not on the core) was read out of those tests.
- **The core needs nothing of Qualcomm's to program.** Ubuntu's clang 18 and lld compile and link a bare-metal Hexagon program. The open toolchain Qualcomm publishes (`quic/toolchain_for_hexagon`, BSD-3-Clause) adds picolibc and is for Linux hosts; its macOS builds are "omitted, they'll return in a future release".
- **What the Hexagon's first run took.** Beyond the unpublished tag: the Hexagon components do not compile as C++20 (a format string built at run time, 📮 in [upstream.md](../upstream.md)); the core wants its global registers and a TLB beside it, and is told where to start through the global registers; QBox's SystemC is shared and its `main` wants an `sc_main` to exist; and the CCI broker has to exist before any component. The ISS spike had met the last two. The program ran first time once it was loaded at the start address, and prints one warning that the coprocessor is disabled, which is right.
- **The simulated clock barely moves.** The whole Hexagon run takes 11 ns of simulated time: the core polls and multiplies inside its quantum, and nothing else in the bench asks for time. A platform that puts a Hexagon beside a CPU model would need the two to agree on time, which is the ISS spike's quantum question again.
- **numpy's `int8 @ int8` wraps.** It accumulates in the operands' type, so the numpy flavour widens to `int32` first, which is what the hardware does. A learner who hands the block an operation in Python will meet the same thing.
- **The executor is the right door.** The numpy flavour needed no change to `PythonExecutor`: a SystemC thread hands it a job and waits, as `ScriptedBusMaster` does for a script. Embedding an interpreter in a C++ test needed only a `PyConfig` naming the virtual environment's Python, so that numpy is found.

## What was set aside without a build

The plan passed these over on an impression (too big, too quiet, tied to a core of its own). Each was read far enough to say whether the impression was right.

| | Licence | What the open model is | How it is driven | Alive? | What it would cost here |
|---|---|---|---|---|---|
| **NVDLA** (NVIDIA) | NVIDIA Open NVDLA Licence (hw, vp); BSD-3-Clause and GPL-2.0 (sw) | A SystemC/TLM-2.0 C model (`hw/cmod`, 214 files) beside the RTL, and a virtual platform (`nvdla/vp`) built on a 2018 QBox and SystemC 2.3.0. A Linux driver (DRM) and a user-mode runtime. | A register bus of its own (CSB) plus an AXI master and one interrupt; firmware programs register groups per layer. | ❌ hw 2018, vp 2018, sw 2019. | The one real SystemC NPU in the open. Its cmod would need porting to SystemC 3.0 and C++20 (unverified), an adapter from CSB to TLM, and the impression that it is too big was right: it is a whole deep-learning pipeline, and a learner's first NPU should fit on one page. It is the right thing to read when M19 wants a second, realistic tier. |
| **VTA** (Apache TVM) | Apache-2.0 | A plain C++ functional simulator (`fsim`, one file) and a Chisel RTL with a Verilator wrapper, both depending on TVM's runtime. | An instruction stream in DRAM, kicked off through registers. | ❌ Removed from TVM in 2024 ("not actively maintained"); its own repo last changed in 2022. | Small and well shaped, but it comes with TVM's runtime and without maintenance. Not borrowed. |
| **Gemmini** (UC Berkeley) | BSD-3-Clause (RTL); the Spike plugin has no licence file | Chisel RTL and a functional model that is a Spike plugin (`libgemmini`). | RISC-V custom instructions through a RoCC port on a Rocket or BOOM core: it is part of the CPU, not a block on the bus. | ✅ RTL 2025, plugin 2025. | The impression that it is tied to a core of its own was right. socpuppet's CPU is DBT-RISE, which has no RoCC port, and an accelerator that is an instruction set extension has no slot to sit in. Not borrowed. |

## Cost

| | Lines | Notes |
|---|---|---|
| Draft slot | 30 | A concept. |
| Doorbell | 200 logic and registers, 70 as a block on the bus | Would be `regs/npu_doorbell.rdl` plus the generated files in the main tree. |
| 🎭 Behavioral NPU | 85 logic, 30 shell, 55 plain multiplier | The shell is `CommandDevice`, reused as it is. |
| 🧵 numpy flavour | 50 | Plus 25 lines of CMake to embed Python in a test. |
| QBox Hexagon | 110 wrapper, 80 C and 10 assembly for the program, 80 CMake | Plus a Dockerfile and a build script with three source patches, and QBox's 2.5 GB build. |
| Tests | 250 | Shared bench, four behavioral tests, one doorbell test, one Hexagon test. |

## Recommendation

🎭 **Build the behavioral NPU of our own, on the compute die, with both flavours.** Four facts decide it.

1. **It is what the firmware sees either way.** The host's side of a Hexagon-based NPU is the same doorbell, the same descriptor and the same interrupt. What a Hexagon adds is a second program to write, in a second toolchain, for a core with no open RTOS, and that is a cost to the person booting their firmware, not a gain.
2. **It is in the wheel.** QBox is GPL-2.0 underneath, so a Hexagon would be the one block in Phase 4 that a `pip install` does not bring, and M19's exit (an inference run from the host, checked from Python) would need Docker.
3. **Linux is simpler.** One memory region and one interrupt is a UIO device with no kernel code. FastRPC is a kernel driver, a library and a closed shell on the DSP.
4. **The numpy flavour is the teaching tool.** A block whose operation is a Python function is the puppet show at its most literal: a learner can replace the multiply with a convolution, or with a deliberately wrong answer, from the strings. The C++ flavour is the fast default and the one that goes in the wheel with no numpy; the Python one is a `Multiplier` away.

**Which die**: the compute die, behind the host's bus and, in M19, behind its own IOMMU. The question of a die of its own was asked in case the AI processor were a whole subsystem with a processor and memory of its own, which a Hexagon would be. A behavioral block has no reason to be on the far side of a link, and the link would only add a tier to a model that has none. [roadmap.md](../roadmap.md#open-decisions) keeps "a die of its own" open for after M16.

**What to keep of the Hexagon**: the slot and the doorbell were designed for it and work with it, so it stays a candidate for an optional, from-source component later, as QBox's RISC-V core does on the to-do list. The recipe in `spikes/npu/hexagon/` is where that starts.

💡 If the decision is the Hexagon after all: wire the doorbell's `kick` into the L2VIC so that the program sleeps instead of polling, give the core a quantum worth of time per `COMPLETE`, and plan for FastRPC's open halves in M20.

## Not exercised

- The Hexagon's interrupt controller (L2VIC): the program polls `PENDING`. Its HVX vector unit, which is what makes a real Hexagon fast at this.
- A descriptor the Hexagon cannot reach (above 4 GiB), which the program answers with `ERROR` but no test rings.
- QBox on macOS, and the Hexagon test under socpuppet's `Platform` (QBox cannot share a program with SCC, so the bench is wired by hand).
- Anything but one matrix multiply: no queue of descriptors, no second operation, no fault other than an unreadable descriptor.
- The numpy flavour from a Python process rather than an embedded interpreter, which is how it would ship.
- Linux, on either side.

## For docs/upstream.md

📮 Two entries for QBox, added with this spike: the lock file's unpublished libqemu tag, and the Hexagon components that do not compile as C++20. Nothing for numpy or clang.

## Decisions

Made on 2026-10-10 by the maintainer, after the report.

- **The AI processor is 🎭 the behavioral NPU of ours**, on the compute die, as recommended. The Hexagon stays what the recommendation made it: a candidate for an optional, from-source component later, starting from `spikes/npu/hexagon/`.
- **Its arithmetic is Python's, and the library is numpy for now.** The spike's recommendation had the C++ loop as the default and numpy as the teaching flavour. The decision turns that round: 🧵 the block's operation is a Python function, because that is what makes the puppet show literal, and numpy is the library it is written with because it installs everywhere, in a tenth of a second.
- **The library has to be interchangeable.** The block, its register map, its DMA and its driver know that the operands and the product are arrays in the host's memory, and nothing more. The seam is in Python: the block hands the operands to a Python callable as buffers and takes the product back as one, so numpy, torch or anything that speaks the buffer protocol or DLPack can stand behind it, and swapping is a Python function, not a C++ change. M19 plans where that callable is set (on the board, or from the strings at run time) and whether numpy is a dependency of the wheel or an extra.

💡 **Why not torch now.** It was asked and measured the same day, with the spike's 256 by 256 multiply. On this project's own development machine, an Intel Mac with Python 3.13, torch does not install: PyTorch stopped shipping Intel macOS wheels in 2024 and never shipped one for Python 3.13 on it. In a Linux container, torch 2.14.1 CPU-only was 769 MB on disk against numpy's 43, imported in 1.3 s against numpy's 0.1 s, and started a 14-thread pool inside the process. It was faster: 2.7 ms for the multiply widened to int32 against numpy's 14.7 ms, and `torch._int_mm`, which is the real thing (int8 operands, int32 accumulate, what an NPU's MAC array does), under 0.1 ms. That speed is not what the exit test is about, and the ops torch would bring (quantized convolutions, and ExecuTorch as the way models reach real NPUs, Hexagon included) are M19's question or later. The interchangeable seam is there so that the day that question has a good answer, it is a Python function away. ⚠️ Plain `int8 @ int8` wraps in torch as it does in numpy: the result has the operands' type.
