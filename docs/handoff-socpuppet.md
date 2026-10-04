# Handoff: socpuppet — open-source SystemC/TLM virtual platform (chiplet host + NVMe SSD)

**Date:** 2026-10-03 / **Source:** claude.ai conversation

## Goal
Build `socpuppet`, an open-source educational virtual platform in which a chiplet-based host (a compute die and an IO die joined by a UCIe-style die-to-die link) and an NVMe SSD controller each run their own Zephyr firmware, all inside one SystemC simulation. It must be controllable as a Python object (the name: you pull the SoC's strings from Python), unit-tested with GoogleTest, and clear enough to teach how commercial VP flows (e.g. Synopsys Virtualizer) work using only open tools. Every block must be swappable for a simplified stand-in, so the platform is built and tested incrementally rather than all at once.

## Context
- The repo is empty; this brief is the starting spec.
- The project should demonstrate industry VP practice: SoC and chiplet integration from TLM models (plus some RTL), multi-die boot flows, firmware bring-up before silicon, PCIe/NVMe, die-to-die interconnect, validation scenarios, and reusable methodology/automation.
- Prior art to evaluate and reuse where licenses allow:
  - **riscv-vp** (Univ. Bremen, MIT): SystemC TLM-2.0 RV32/RV64 GC ISS with Zephyr support and a GDB stub.
  - **VCML** (MachineWare, Apache-2.0): TLM-2.0 modeling library (registers, IRQ ports, memories, UARTs, PCI endpoint models).
  - **QBox** (Qualcomm): QEMU CPUs as SystemC modules; pulls in QEMU (GPL-2.0).
  - FEMU, MQSim, SimpleSSD/Amber: SSD simulators, useful for FTL and NAND timing ideas only.
- Zephyr's in-tree NVMe host driver requires PCIe multi-vector MSI-X. Zephyr mainline has RISC-V AIA (APLIC/IMSIC) interrupt drivers, but whether PCIe MSI-X is wired to them on RISC-V is unverified.

## Decisions

### Modularity (foundational; everything else builds on this)
- Slot-based architecture: every block (each CPU + its firmware, SSD, NAND, PCIe link, D2D link, peripherals) is defined by an interface contract (TLM sockets, IRQ/reset signals, config parameters) and instantiated by name through a C++ component registry that Python drives. Because any block can then run as a stand-in or a full model without its neighbors changing.
- Fidelity tiers where useful: **stub** (accepts traffic, returns fixed data, logs), **behavioral** (functionally correct, no internal structure), **full** (the real model, e.g. ISS + firmware). Because it lets each block start simple and grow.
- CPU stand-in = scripted bus master: a C++ TLM initiator that runs an op sequence (read, write, wait for IRQ, wait time, expect value), plus a Python adapter where a Python generator yields those ops. Because the rest of the platform can be built and tested before any ISS or firmware exists. The C++ version keeps gtest free of Python; `sc_start` releases the GIL and Python stand-in callbacks re-acquire it.
- Behavioral NVMe device: a RAM-backed C++ NVMe controller that processes commands itself, with no SSD CPU or firmware. Because host-side bring-up can proceed before the SSD exists, and it later serves as the reference model for checking the full SSD.
- Ideal NAND stand-in (no timing, no erase rules) alongside the realistic NAND model, because early SSD firmware work shouldn't wait on NAND fidelity.
- Contract tests: each interface has one gtest suite (typed tests) that every implementation must pass. Because that is what guarantees a stand-in and a full model are truly interchangeable.
- Each milestone swaps at most one stand-in for a full model, so a failure points at the new block.

### Platform
- Fully open-source toolchain, no Virtualizer, because learners must be able to build it for free.
- SystemC 3.0.x + TLM-2.0 loosely-timed, with temporal decoupling and DMI for memories, because LT is the industry norm for software bring-up VPs and keeps Zephyr boots fast.
- RISC-V everywhere: RV64 host compute die (64-bit PCIe windows/BARs, closer to real hosts), RV32IMAC for the SSD controller and the IO-die management core (mirrors embedded controller cores), because Zephyr's generic RISC-V drivers (machine timer, PLIC, NS16550 UART) need little modeling and open SystemC ISSs exist.
- One process, one SystemC kernel for every die and the SSD, because it gives deterministic, single-stepped co-debug of all firmware images. Keep PCIe and D2D links clean module boundaries so a multi-process split stays possible.
- Host built as composable dies from the start, with the D2D link slot first filled by a zero-latency pass-through stand-in. The later chiplet split is then a config change needing no changes to host Zephyr applications, which is the "reusable platform infrastructure" story the project exists to show.
- Chiplet partitioning: compute die = RV64 CPU, local DRAM, interrupt controller. IO die = PCIe root complex, UART, timers, RV32 management core. Host DRAM stays on the compute die so instruction fetch and DMI never cross the link (simulation speed).
- Full D2D link at transaction level: one link module per die with a link state machine (reset → training → active, plus error/retrain), configurable latency and bandwidth, a sideband channel for management register access, and error injection hooks. The mainband carries MMIO, DMA and MSI writes. Because this captures what firmware and system validation observe (bring-up sequencing, latency, failures) without PHY detail.
- The IO-die management core runs Zephyr, trains the D2D link, then releases the compute die from reset, because multi-die boot sequencing is the defining chiplet bring-up problem.
- PCIe at transaction level (TLM generic payload + extension carrying config/mem space, requester ID), not TLP/link level, because drivers and firmware only observe config, MMIO, DMA and MSI semantics. Root complex provides an ECAM window, MMIO window, inbound DMA to host memory, and MSI-X as memory writes.
- NVMe HW/FW split in the full SSD: hardware models implement config space, BAR0 NVMe registers and doorbells, MSI-X table, an SQE fetch engine (into device SRAM + IRQ to SSD CPU), a host↔buffer DMA engine and a completion poster. SSD Zephyr firmware does command decode, admin commands, PRP handling and the FTL. Because the interesting protocol logic then lives in readable firmware, mirroring real controllers.
- Realistic NAND model with channel/die/plane/block/page geometry, tR/tPROG/tBERS as annotated delays, erase-before-write enforcement, sparse or file-backed storage, and bad-block/bit-error injection hooks, because FTL behavior is the main learning target on the SSD side.
- Python API via pybind11, packaged with scikit-build-core: platforms are composed in Python (pick an implementation per slot, connect sockets, map addresses, wire IRQs) and then run, with Python stand-ins, ELF loading per CPU, run/run_until/step, memory and register peek/poke, UART capture, NAND inspection, link-state control, fault injection and stats.
- The SystemC kernel is a process-global singleton that cannot be re-elaborated, so: one Platform per process; gtest tests registered via `gtest_discover_tests` (CTest runs each in its own process); pytest tests needing fresh platforms use subprocess isolation (e.g. pytest-forked). Model logic lives in plain C++ classes separate from SystemC wrappers so most unit tests need no kernel at all.
- Platforms are described in Python only, with no separate config format (no YAML): the Python platform description is the single source of truth for slot implementations, memory maps, cross-die address windows and IRQ wiring, and the same description generates each board's Zephyr devicetree, because hand-maintained copies drift. Python is already required (the API, Zephyr's tooling), and gem5 uses the same Python-composes-C++ pattern.
  - All construction happens before `sc_start` (SystemC elaboration), so the builder has an explicit build → run lifecycle and rejects topology changes after build.
  - A description must be loadable without starting a simulation, so the Zephyr build can generate devicetree from it (e.g. a CMake step invoking a `socpuppet` devicetree generator).
  - C++ never parses platform descriptions: gtest contract tests instantiate blocks directly, and full-platform tests run from pytest. A built platform can dump its resolved description to JSON for logging and run reproducibility.
- C++20 everywhere to start: models, tests, bindings, and SystemC itself built from source as C++20. SystemC's link-time API check encodes the C++ standard (SC_CPLUSPLUS), so the library and everything linking it must match. Good C++20 uses: concepts for slot contracts, `std::span` for DMA buffers, coroutines so the C++ scripted bus master mirrors the Python generator stand-ins. Toolchain: GCC 13+ (Ubuntu 24.04 default) or a recent Clang.
  - If a component won't build as C++20, report it and ask before changing anything. Known fallback: build SystemC as C++17, pin `SC_CPLUSPLUS=201703L` on the SystemC CMake target so every consumer inherits it, override only the offending targets to C++17, and keep any headers those targets include C++17-clean.
- CMake, deps via FetchContent (SystemC, GoogleTest, pybind11, plus SCC and the Boost, fmt, spdlog and yaml-cpp it needs; added at M0 for SCC's TLM router and SCP-style logging). The repo is a Zephyr module providing out-of-tree boards `socpuppet_host` (monolithic), `socpuppet_compute`, `socpuppet_iomgr` and `socpuppet_ssd`, built with west and the Zephyr SDK.
- MIT license (decided at M0; this brief first proposed Apache-2.0). SystemC, SCC and Zephyr are Apache-2.0, which MIT code may depend on. GPL code (e.g. QBox/QEMU) stays out of the core.

## Constraints
- Learning tool first: readability and documentation beat raw speed. Each model gets a short doc explaining the real hardware it represents and what it simplifies.
- Stand-ins are first-class, documented and kept working, with CI running configurations that use them. They double as teaching aids: a learner can study one block (e.g. the FTL) with everything around it simplified.
- Every model unit-testable in isolation with gtest; every milestone ends with an automated end-to-end test in CI (GitHub Actions, Ubuntu LTS).
- No proprietary tools, IP or NDA material. The UCIe spec evaluation copy is licensed for non-commercial internal evaluation only, and the PCIe Base spec is not freely available, so model "UCIe-style" and PCIe behavior from public sources (white papers, published papers, OS driver code), never copy spec text or register tables, never claim compliance, and say so in the docs. NVMe specs are public and may be followed directly.

## Suggested approach
Each step names the stand-in it replaces.
1. Scaffold + infrastructure: CMake, deps, CI, LICENSE, `docs/architecture.md`; interface definitions, component registry, Python platform builder and devicetree generator, scripted bus master (C++ + Python adapter), memory, IRQ/reset signals, pass-through link, transaction tracing, contract-test harness.
2. ISS spike (time-boxed; step 3 does not wait on it): compare riscv-vp's ISS, a VCML-based approach, and a minimal in-house ISS behind the CPU slot interface (TLM initiator + IRQ inputs + GDB hooks). Criteria: in-process, LT + DMI, boots Zephyr, license fit, C++20 compatibility (preferred, not required), build simplicity. Report before committing.
3. PCIe + behavioral NVMe, no CPUs yet: root complex, endpoint config space, BARs, MSI-X and the behavioral NVMe device, driven by a Python "host driver" stand-in. Milestone: Python creates queues, runs Identify and completes block reads/writes.
4. Host CPU + Zephyr (replaces the host stand-in): ISS, ELF loader, DRAM, UART, timer, PLIC. Milestones: Zephyr `hello_world` and `synchronization` on `socpuppet_host`, then Zephyr NVMe block I/O against the behavioral NVMe device. Resolve the MSI-X question here.
5. Full SSD hardware with a firmware stand-in (replaces the behavioral NVMe device): NVMe frontend HW, DMA engine, flash controller and ideal NAND, with the SSD CPU slot filled by a Python "firmware" stand-in. Milestone: the step 3 host tests and NVMe contract tests pass against it.
6. SSD CPU + Zephyr firmware (replaces the firmware stand-in): RV32 ISS, SRAM, DRAM buffer, UART, timer; firmware with admin path and a page-mapped FTL. Milestone: Zephyr host ↔ Zephyr SSD block I/O, with Python checking data against the behavioral device.
7. Realistic NAND (replaces ideal NAND): timing, erase-before-write, fault hooks; FTL gains garbage collection. Milestone: the step 6 test passes under sustained writes.
8. Chiplet split (replaces the pass-through link): D2D link model, PCIe and UART move to the IO die, management core added (scripted stand-in first, then Zephyr link-training/reset-release firmware). Milestone: the step 6 end-to-end test passes unchanged, with every NVMe command, DMA and MSI crossing the D2D link.
9. Validation scenarios: multi-die boot sequencing, link down/retrain during I/O, cross-die data integrity, bad blocks, power loss, IOPS/latency stats, transaction tracing.
10. Stretch: a Verilator-compiled RTL block (e.g. CRC/ECC engine in the SSD datapath) integrated through a TLM-to-signal adapter; a power/telemetry model (voltage regulator + sensors) on the IO die controlled by the management firmware.

## Open questions
- ISS choice (outcome of step 2).
- Build on VCML vs. a thin in-house layer on raw SystemC/TLM: VCML saves effort, raw SystemC is more transparent for learners.
- Host MSI-X on RISC-V: verify Zephyr mainline support. If missing, either add RISC-V PCIe MSI hooks to Zephyr (a possible upstream contribution) backed by an IMSIC-like or simple MSI-to-PLIC bridge model, or write a minimal host NVMe driver in this repo. After step 8, MSI writes also cross the D2D link.
- An extra firmware fidelity tier: Zephyr built for `native_sim` with its MMIO accesses routed into the VP, for fast firmware iteration without an ISS.
- D2D mainband protocol: raw memory-mapped transactions vs. a PCIe/CXL-like protocol layer over the link.
- One compute die, or two to show multi-die scaling.
- Moving host DRAM onto the IO die (server-CPU style) as a later configuration.
- Zephyr version to pin (AIA drivers may only exist in recent releases).
- Single- vs multi-core SSD controller (real controllers split frontend/FTL/backend across cores).

## Out of scope (for now)
- Cycle-accurate or AT timing; PCIe/UCIe PHY, electrical and TLP/flit-level modeling.
- Linux on the host.
- Ethernet, CXL, and DDR/HBM timing models (candidate later extensions).
- GUI.

---

**Kickoff prompt:** Read this brief and implement it. Start with step 1 (scaffold and stand-in infrastructure), then run the step 2 ISS spike and report findings with a recommendation before building any CPU-based model; step 3 may proceed in parallel. Ask before deviating from the Decisions section.
