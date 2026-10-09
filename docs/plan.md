# socpuppet — high-level plan (milestones and tasks)

## Context

`docs/handoff-socpuppet.md` specifies an open-source SystemC/TLM virtual platform: a chiplet host (RV64 compute die, plus an IO die with an RV32 management core, joined by a UCIe-style D2D link) and an NVMe SSD (RV32 controller). Each runs its own Zephyr firmware inside one simulation that is composed and driven from Python. When this plan was written, the repo held only that brief, a README and a LICENSE.

This plan keeps the handoff's Decisions and reorders its suggested steps around how the platform gets consumed. Assumption: a "customer" is a firmware team owning one image (host, SSD, or IO-die manager). Each team first needs to boot its own firmware on its own subsystem with everything else stood in. The full multi-firmware bootchain comes after that.

1. **Foundation**: infrastructure and stand-ins, no CPUs.
2. **Standalone subsystem boot**: three independent tracks, one per firmware image.
3. **Full bootchain**: combine the images, swapping one stand-in per milestone.
4. **Fidelity and validation.**

Changes from the handoff's step order:

- Step 6 is split. SSD firmware is first proven against the Python host stand-in (M4); host ↔ SSD becomes the first integration milestone (M6).
- Step 8 is split. The D2D link and IO-manager firmware are brought up standalone with the compute die stood in (M5), before the real host is split into dies (M7) and the manager firmware joins it (M8).
- Step 7 (realistic NAND) moves after the bootchain because nothing on that path needs it. It can be pulled forward any time after M4.

## Milestone map

| # | Milestone | Handoff step | Stand-in replaced | Needs | Exit test (automated, in CI) |
|---|---|---|---|---|---|
| M0 | Scaffold + stand-in infrastructure | 1 | none | none | Python-scripted bus master reads/writes memory through the pass-through link |
| M1 | ISS spike (decision gate) | 2 | none | M0 | Report + recommendation; candidate boots Zephyr `hello_world` behind the CPU slot |
| M2 | PCIe + behavioral NVMe, no CPUs | 3 | none | M0 | Python host stand-in creates queues, runs Identify, reads/writes blocks |
| M3 | **Host boots standalone** | 4 | Python host → RV64 + Zephyr | M1, M2 | a) `hello_world`, `synchronization` on `socpuppet_host`; b) Zephyr NVMe block I/O against behavioral NVMe |
| M4 | **SSD boots standalone** | 5, 6 (SSD half) | behavioral NVMe → SSD hardware; then Python firmware → RV32 + Zephyr | M2, CPU kit from M3a | M2 host tests + NVMe contract tests pass against the Zephyr SSD firmware |
| M5 | **IO manager boots standalone** | 8 (pulled forward) | pass-through → D2D link; then scripted manager → RV32 + Zephyr | M0, CPU kit from M3a | Firmware trains the link and releases reset; compute-side stand-in round-trips MMIO across it |
| M6 | Host firmware ↔ SSD firmware | 6 (milestone) | behavioral NVMe → full SSD, under the Zephyr host | M3, M4 | Zephyr host ↔ Zephyr SSD block I/O, data checked against the behavioral device |
| M7 | Chiplet split | 8 (hardware) | pass-through → D2D link, under the real host | M5a, M6 | M6 test passes with the host app unchanged; trace shows every NVMe command, DMA and MSI crossing D2D |
| M8 | **Full bootchain, three firmwares** | 8 (firmware) | scripted manager → Zephyr manager firmware | M5b, M7 | One test asserts boot order across three UARTs, then end-to-end data integrity |
| M9 | Realistic NAND + garbage collection | 7 | ideal NAND → realistic NAND | M4 | M4/M6 tests pass under sustained writes |
| M10 | Validation scenarios | 9 | none | M8, M9 | Scenario suite (below) |
| M11 | Stretch: RTL block, power/telemetry | 10 | none | M8 | To be defined |

```text
M0 ─┬─ M1 (ISS gate) ── M3 host ──────────────┐
    ├─ M2 (PCIe + behavioral NVMe) ── M4 SSD ─┼─ M6 ── M7 ── M8 ── M10
    └─ M5 IO manager (5a link, 5b firmware) ──┘       M9 NAND: any time after M4
```

M3, M4 and M5 are independent of each other apart from the shared CPU kit, so they can run in parallel or in any order. Suggested serial order: M3, M4, M5.

## Phase 1: Foundation

### M0 — Scaffold + stand-in infrastructure

- Repo: CMake (C++20), FetchContent for SystemC 3.0.x / GoogleTest / pybind11, scikit-build-core packaging, GitHub Actions on Ubuntu 24.04, `docs/architecture.md`.
- Slot contracts as C++20 concepts (TLM sockets, IRQ/reset signals, config parameters) and the component registry that instantiates blocks by name.
- Python platform builder: build → run lifecycle, one Platform per process, description loadable without simulating, JSON dump, run / run_until / step, peek / poke.
- Devicetree generator skeleton driven by the Python description.
- Core blocks: memory with DMI, IRQ and reset signals, pass-through link, transaction tracing.
- Scripted bus master: C++ coroutine version plus the Python generator adapter (GIL released in `sc_start`).
- Test harness: gtest typed contract tests via `gtest_discover_tests`; pytest with per-test process isolation.
- Router and logging come from SCC (Minres SystemC-Components): `scc::router` behind a registry adapter, and SCP-style logging macros through SCC's SCP layer.
- Built test-first (`.claude/skills/tdd`) wherever there is behavior to specify.
- Housekeeping, settled: the license stays MIT. macOS is a supported dev host alongside Ubuntu 24.04, and a devcontainer provides the CI environment.

### M1 — ISS spike (time-boxed; M2 does not wait on it)

- Compare riscv-vp's ISS, a VCML-based approach and a minimal in-house ISS behind the CPU slot interface, on the handoff's criteria (in-process, LT + DMI, boots Zephyr, license, C++20, build simplicity).
- Report with a recommendation, and stop for a decision before any CPU-based model is built. The same report settles VCML vs. a thin in-house layer and proposes the Zephyr version to pin.

### M2 — PCIe + behavioral NVMe, no CPUs

- PCIe TLM extension (config/mem space, requester ID); root complex with ECAM window, MMIO window, inbound DMA and MSI-X as memory writes; endpoint config space, BARs, MSI-X table.
- Behavioral NVMe device: RAM-backed, plain C++ core with a thin SystemC wrapper.
- Python "host driver" stand-in, and the NVMe contract suite that every later NVMe implementation must pass.

## Phase 2: Each subsystem boots its firmware standalone

Every track delivers the same kit to its firmware team: a Python platform description with that subsystem at full fidelity and its neighbors as stand-ins, the Zephyr board, a sample app, a pytest boot test, UART capture and GDB attach, and a short "boot your firmware here" doc.

The kit arrives as a Python package, because that is how a firmware developer gets the model: from M3 on, `uv add socpuppet` (or `pip install socpuppet`) pulls a prebuilt wheel for Linux and macOS with no compiler needed. That means cibuildwheel, PyPI publishing and versioning land with M3, and the Zephyr boards must be reachable from the installed package. M3a builds and tests the portable wheels in CI with cibuildwheel. Publishing to PyPI and versioning follow in M3b or a step of their own, so that nothing irreversible goes out with the first CPU. M0 keeps the road open by building the wheel in CI and testing it installed with both uv and pip.

### M3 — Host subsystem

(board `socpuppet_host`; SSD = behavioral NVMe, D2D = pass-through)

- a) CPU kit, built once and reused by M4 and M5: DBT-RISE-RISCV behind the CPU slot (RV64 and RV32IMAC), ELF loader, DRAM, a 16550-style UART with Python capture, machine timer, PLIC, GDB hook. The three peripherals are borrowed from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals) behind adapters of ours, each held to a contract suite written first. Zephyr module and board with devicetree generated from the platform description. Exit: `hello_world`, `synchronization`.
- b) PCIe enumeration from Zephyr; resolve the MSI-X-on-RISC-V question (verify mainline, else an MSI bridge model plus Zephyr hooks, or a minimal in-repo NVMe driver). Exit: Zephyr NVMe block I/O against the behavioral device.

### M4 — SSD subsystem

(board `socpuppet_ssd`; host = Python host stand-in from M2, NAND = ideal)

- a) SSD hardware with a "firmware" stand-in in the CPU slot: NVMe frontend (BAR0 registers and doorbells, SQE fetch engine, completion poster, with configuration space and the MSI-X table left to the PCIe endpoint M2 built), DMA engine, flash controller, ideal NAND behind a NAND slot with a contract suite of its own. The stand-in is a script, in Python for pytest and as a C++ coroutine for the contract rig. Exit: M2 host tests and NVMe contract tests pass.
- b) RV32IMAC CPU, SRAM, DRAM buffer, UART, timer, PLIC. Exit: Zephyr `hello_world` on `socpuppet_ssd`.
- c) SSD firmware, with drivers for the three devices in socpuppet's Zephyr module: admin path, PRP handling, page-mapped FTL. Exit: the same M2 tests pass against the firmware, with data checked against the behavioral device.

### M5 — IO-die manager subsystem

(board `socpuppet_iomgr`; compute die = scripted stand-in held in reset)

- a) D2D link model: one link module per die, link state machine (reset → training → active, error/retrain), configurable latency and bandwidth, sideband register channel, error injection hooks, compute-die reset control. D2D contract suite passed by both pass-through and full link. Manager slot filled by a Python script that trains the link over sideband.
- b) RV32IMAC management core, UART, timer; Zephyr link-training and reset-release firmware. Exit: firmware boots, trains the link, releases reset, and the compute-side stand-in then reaches IO-die MMIO across the link.

## Phase 3: Full bootchain

### M6 — Host firmware ↔ SSD firmware

(monolithic host, pass-through link)

- Two ELF images in one simulation, reset/ready sequencing (host waits on CSTS.RDY while SSD firmware boots), two UART captures, two GDB ports, quantum tuning with two ISSs.

### M7 — Chiplet split

(manager = the M5a script)

- Host description becomes compute die + IO die; PCIe root complex and UART move to the IO die; board `socpuppet_compute` generated from the same description; cross-die address windows.
- Host Zephyr application source stays unchanged, which is the reuse claim the project exists to show.

### M8 — Full bootchain

- Sequence under test: power-on → IO manager boots → trains D2D → releases compute die → host Zephyr boots across the link → PCIe enumeration → NVMe enable against the SSD firmware → block I/O.
- Three-image co-debug walkthrough in the docs.

## Phase 4: Fidelity and validation

### M9 — Realistic NAND

Geometry, tR/tPROG/tBERS delays, erase-before-write, sparse or file-backed storage, bad-block and bit-error hooks, NAND contract suite; FTL gains garbage collection.

### M10 — Validation scenarios

Boot-sequencing variants and failures, link down/retrain during I/O, cross-die data integrity, bad blocks, power loss, IOPS/latency stats.

### M11 — Stretch

Verilator RTL block behind a TLM-to-signal adapter; power/telemetry model on the IO die.

## Decisions deliberately left open

| Decision | Must be settled by | Default until then |
|---|---|---|
| D2D mainband protocol (raw memory-mapped vs. PCIe/CXL-like layer) | M5a | raw memory-mapped transactions |
| Does "bootchain" include a ROM/bootloader stage per image? (not in handoff; ELFs are loaded from Python) | After M8 | no bootloader |
| `native_sim` firmware tier | Optional, any time after M3 | not built |
| Second compute die; host DRAM on the IO die | After M8 | one compute die, DRAM on compute die |

## Verification

- Every milestone ends with the automated end-to-end test in its "Exit test" column, run in GitHub Actions on Ubuntu LTS.
- Every slot interface has one gtest contract suite; a stand-in and its full model both pass it before either is used in an integration milestone.
- Stand-in configurations from earlier milestones stay in CI, so the standalone kits from M3 to M5 keep working after M6 to M8 land.
- Model logic lives in plain C++ classes, unit-tested without the SystemC kernel. A borrowed model is the exception: it is tested through its contract suite, behind its adapter.

## Status

**M0, M1, M2, M3 and M4 are done.** M5 (the IO-die manager) and M6 (the Zephyr host with the Zephyr SSD) are both open: M6 needs nothing from M5.

What M4c delivered, and with it M4: the SSD runs its own firmware. The exit test is `tests/python/test_m4_exit.py`: M2's three scenarios with Zephyr on the SSD's CPU and the host's script unchanged, and then the SSD and 🎭 the stand-in drive side by side in one platform, given the same thirty overlapping writes and read back whole. `examples/ssd_firmware_hello.py` is the show to run by hand, and [boot-your-firmware.md](boot-your-firmware.md) has a section on bringing up SSD firmware of your own.

- **The firmware**, `firmware/ssd`: a Zephyr application of about nine hundred lines, comments and all, with a file for each section of the Python stand-in. One thread, one command at a time.
- **Three drivers in the Zephyr module**, in Zephyr's device model. The flash controller's is a driver of Zephyr's own flash class: a NAND page is the write block, and a NAND block is what the class calls a page. It is held to Zephyr's own test of a flash driver, built unchanged by `firmware/flash_test`. The frontend and the DMA engine have small APIs of their own, because Zephyr has no class that is either.
- **One suite for two firmwares.** `tests/python/test_ssd_firmware.py` runs every test twice, with the script and with Zephyr: 39 tests, 78 runs. Zephyr passed them as they stood. Each tier was checked with mutations, so that a broken firmware is known to fail. What only one of the two does has a file of its own: the script's table, which Python can look at, in `test_ssd_stand_in_firmware.py`, and what Zephyr says on its console in `test_ssd_zephyr_firmware.py`.
- **The table is in the SSD's buffer**, after a page of scratch and a page of the drive: four bytes for each page of the drive, made empty at every start. That settles what M4a left open. It is in no NAND page, so it does not outlive the firmware, and nothing can restart the SSD's CPU yet to show it.
- **Lint reads C.** The firmware and the drivers are held to Zephyr's style by a `.clang-format` in each of their directories ([style.md](style.md)).
- **Two entries for [upstream.md](upstream.md)**, both about Zephyr's flash API: a write block size that a driver cannot learn from its chip without a `memcpy`, and offsets that stop at 2 GiB on a 32-bit CPU. The firmware refuses a NAND bigger than that.
- **Firmware that cannot start says why.** A NAND too big for the flash API, a flash controller that reports an error or never answers, a NAND page bigger than the driver was built for: each is a sentence on the console that says what to change, and a test.

What M4c did not do, that the plan said or implied:

- ⚠️ **The C++ NVMe contract does not run against the Zephyr firmware.** The milestone map's exit says "NVMe contract tests pass against the Zephyr SSD firmware". The contract rig is C++ with no CPU kit and no ELF loader in it, and it holds the SSD's hardware with the C++ stand-in for firmware. What holds Zephyr is the Python suite above, which has the firmware's share of the contract (ready and not ready, every status a command can be refused with, data through PRP lists, a reset) and not the hardware's share, which does not depend on the firmware. Running the contract itself against an image wants the rig built from the registry with a CPU in it, and CI's C++ tests given the firmware images. It is in the to-do list.
- **No register header shared by the models and the drivers.** The plan floated one C header for both. The drivers have their own definitions, a dozen lines each, and the tests that run firmware on the models are what keeps the two in step.
- **The Zephyr cases were never marked as expected failures.** The plan had them `xfail` and switched on one behaviour at a time. The firmware was written section by section from the stand-in and the whole suite run against it, which was faster and is weaker as test-first goes: no test was seen to fail before its code existed. The mutations are what stand in for that.

What M4c found:

- **The firmware is the only thing on the SSD that takes time.** A command takes it a millisecond or two, at 100 ns an instruction, and the hardware around it takes none. When DMA and NAND get latencies (M9), the drivers' polling of `BUSY` is the first thing to change. They give a device a tenth of a second and then give up, which is long enough only while nothing takes time: the DMA engine and the flash controller have interrupt lines on the PLIC that no driver uses yet.
- **Start-up grows with the drive.** Making the empty table is half a microsecond of simulated time for each page, a quarter of a second for 2 GiB. The host waits up to the one second `CAP.TO` gives it. A bigger buffer, or a table kept on the NAND, moves that.
- **Zephyr's flash class is a loose fit for raw NAND, and it was kept.** Three things rub. Its write block size is `const`, its offsets stop at 2 GiB on this CPU, and it promises reads of any bytes at any offset, which a controller that fetches whole pages can only do through a page of the driver's own. The first two are in [upstream.md](upstream.md). The third was found by running Zephyr's flash test, after a review asked what held the driver's erase path to anything. An interface of our own that counts in pages would be sixty lines and fit exactly. It would also be one more thing a learner cannot recognise from elsewhere, and it would have no borrowed test. The maintainer's decision is below: the flash class stays.
- **The reviews found what the tests could not.** Six tooling tests had been broken by the lint change, and nobody had run them. A drive over 2 GiB wrapped its offsets silently. Firmware on an SSD with a stuck flash controller printed nothing at all. None of these failed a test that existed.
- **A refused write is a bus fault in Zephyr**, with the refused address in `mtval`. That is the right thing for firmware to see, and it means a driver has to be careful where a stand-in script could look at a response and carry on.

What M4b delivered: the SSD's own controller, and the Zephyr board for it. The exit test is `tests/python/test_m4b_exit.py`: Zephyr's `hello_world`, unchanged, prints `Hello World! socpuppet_ssd/socpuppet_rv32`. [boot-your-firmware.md](boot-your-firmware.md) has a section on the board.

- **The controller**: with no script for its firmware, `add_ssd` gives the SSD the CPU kit that M3a built, as a 32-bit core, with an SRAM, a UART, a timer and a PLIC, and each of the three devices' lines on a PLIC source of its own. Nothing new had to be modelled.
- **In the Zephyr module**: the SoC `socpuppet_rv32`, the board `socpuppet_ssd` with its devicetree generated from the SSD's description as its own CPU sees it, and bindings for the three devices. They have no drivers yet.
- **Nothing in Zephyr or in the CPU had to be worked around.** A 32-bit Zephyr took a devicetree with two address cells as it was, and the core started at an address that is not `0x8000_0000`.
- **No change to the devicetree generator.** The plan expected to have to say which of two memories is the one the firmware runs from. It is the first in address order, and the SRAM is below the buffer.

What M4a delivered: an SSD built the way a real one is, with a script where its firmware will be. The exit tests are the whole NVMe contract against it (`Ssd/NvmeContract` in `tests/cpp/contracts/nvme_test.cpp`) and `tests/python/test_m4a_exit.py`, which is M2's exit test with the stand-in drive swapped out and the host's script unchanged. `examples/ssd_hello.py` is the show to run by hand.

- **Four models**, each a plain C++ core with a thin SystemC wrapper and a page of its own: the [NVMe frontend](models/nvme-frontend.md), the [DMA engine](models/dma-engine.md), the [flash controller](models/flash-controller.md) and 🎭 the [ideal NAND](models/ideal-nand.md).
- **A NAND slot and its contract**, `tests/cpp/contracts/nand_contract.h`, which M9's realistic NAND is to pass. A controller talks to a chip over TLM with an extension that says which operation and which page (`models/nand_link.h`).
- **Two firmware stand-ins.** 🎭 [`sp.SsdFirmware`](models/ssd-firmware.md) is a Python script for the SSD's CPU slot, written to be read. `tests/cpp/support/ssd_firmware.h` is the same firmware in C++ for the contract rig, a test's own.
- **The SSD as a board**, `socpuppet.boards.ssd`: `add_ssd` puts one on a root complex's link, `add_ssd_function` is the same with no PCIe around it, and `ssd()` is the kit, with a scripted host in front.
- **What the stand-in drive and the SSD share**: an NVMe controller's queues (`core/nvme_queues.h`) and the register block it shows its host (`core/nvme_host_registers.h`), both taken out of the behavioral controller, which is now what each command does and little else.
- **No change to the PCIe endpoint, or to the host.**

What planning M4 got wrong, or left to be found:

- **The frontend's registers for its CPU are not the plan's.** There are no per-queue registers: firmware describes one queue and has it created, which is six registers where the plan had seventy-two. "A command is waiting" is a level and not something to acknowledge, so the CPU's line falls and rises once for each command. And a reset is a handshake, which the plan did not have at all and a review found the lack of: see the list below.
- **The flash controller has to be told to identify its chip.** The plan had it ask by itself the first time a geometry register was read, which made a read do something and gave a debugger a different view from the CPU's.
- **The C++ firmware stand-in is not a coroutine script.** It is plain C++ in a simulation thread, with a socket and an interrupt input. It reads as the firmware does, and the contract's host ends the run, so nothing needs the script's operations.
- **The stand-ins keep the FTL's table to themselves**, in a Python dict and in a C++ vector, and not in the DRAM buffer, where the plan had it. A stand-in has somewhere better to keep it than simulated memory. The buffer holds a page of the drive and a page of scratch, 8 KiB of its 4 MiB. Where the table lives is M4c's to decide, for firmware that has nowhere else.
- **Nothing borrowed.** No open model of an NVMe controller split into hardware and firmware was found to put behind an adapter. FEMU, MQSim and SimpleSSD model the whole drive from the host's side, as the stand-in drive does. The layouts are still SPDK's.

Decided on 2026-10-09, at M4's end: **the flash controller keeps Zephyr's flash class.** Its driver stays a driver of that class, held to Zephyr's own flash test, and gets no interface of its own that counts in pages. What the class does not fit is lived with and written down: the three mismatches are in the list above, and two of them in [upstream.md](upstream.md). M9's realistic NAND is the next thing to lean on it, with erase before program.

Decided on 2026-10-08, planning M4:

- **One core in the SSD's controller.** One RV32IMAC runs the command path, the admin commands and the FTL in one Zephyr image. That settles the question this plan had left open until M4b. A real controller splits those over several cores, and a second one can be a milestone of its own.
- **Hardware keeps the queues and firmware makes the decisions.** The NVMe frontend owns everything the host sees and every queue pointer: the registers and doorbells, fetching a command into a slot that the CPU reads, posting its completion, and the interrupt lines. Firmware owns `CSTS.RDY`, decodes each command, and tells the hardware where a queue is once it has agreed to create one. A reset by the host is hardware's to carry out and firmware's to notice. `CAP.TO` says one second, so that a host waits for firmware that is still booting.
- **One command at a time.** The frontend has one slot, and fetches the next command when firmware has posted the completion of the last. A command whose completion queue is full is not fetched, which is what keeps a full queue from being written over.
- **Four new models**: `nvme_frontend`, `dma_engine`, `flash_controller` and `ideal_nand`, each a plain C++ core with a thin SystemC wrapper. The PCIe endpoint is unchanged. The frontend's fetches and the DMA engine's transfers share the endpoint's one way up to the host through a router, which is the arbiter a real controller has in front of its PCIe core.
- **A NAND slot from the start**, with a contract suite, spoken to over TLM with an extension that says read page, program page or erase block. 🎭 The ideal NAND takes no time and lets a page be programmed twice. M9's realistic NAND passes the same suite.
- **The FTL is a page map and nothing more.** A page is 4 KiB, eight of the drive's blocks, the map is a table in the DRAM buffer, and an overwrite programs the same page again. Only the ideal NAND allows that. M9 is where it stops being allowed, and where garbage collection comes in.
- **Two firmware stand-ins, as the host has two drivers**: a Python generator in the package (`sp.SsdFirmware`) for pytest and the examples, and a C++ coroutine in the tests' support code for the contract rig, written from the register tables and sharing nothing with the models.
- **The Zephyr firmware reaches the hardware through drivers in socpuppet's Zephyr module**, with bindings and Kconfig, in Zephyr's device model, and not by writing registers from the application. Zephyr's own flash API is tried on the flash controller first.
- **`boards/ssd.py` becomes the SSD.** M2's behavioral drive moves to `boards/drive.py`, as `add_behavioral_drive`. The host with a drive keeps the behavioral one until M6.
- **A fidelity tier is a choice between two description functions in Python**, `add_behavioral_drive` and `add_ssd`, with or without a firmware stand-in. The registry gains no mechanism for it, and parameter schemas stay where they were: not needed yet.
- **Nothing takes time yet.** DMA, flash and NAND are immediate throughout M4. The DMA engine's registers are where latency starts when a milestone wants it.

The steps, in order. Each ends with its own exit test and a docs commit.

- **M4a**: the NAND and its contract, the flash controller, the DMA engine, the frontend (core, then model), the Python stand-in and the board, the C++ stand-in and the contract rig. Exit: all of the NVMe contract against the SSD, and `tests/python/test_m4a_exit.py`, M2's three scenarios against it.
- **M4b**: `zephyr,sram` goes to the memory that holds the reset vector, devicetree nodes and bindings for the three devices, the controller kit in `add_ssd`, the SoC `socpuppet_rv32` and the board. Exit: `tests/python/test_m4b_exit.py`.
- **M4c**: the drivers, the application in `firmware/ssd/`, then one behaviour at a time against the tests the Python stand-in already passes. Exit: `tests/python/test_m4_exit.py`, with the SSD and the behavioral drive in one platform, given the same writes and read back.

What M3b delivered: stock Zephyr 4.4.2 on the host board finds the drive by scanning the PCIe bus, starts it with its own NVMe driver, and reads and writes blocks. The exit test is `tests/python/test_m3b_exit.py`, which boots Zephyr's own test of its disk interface (`tests/drivers/disk/disk_access`), unchanged. [boot-your-firmware.md](boot-your-firmware.md) says how to build an application of your own for it.

- **The MSI-to-PLIC bridge**, `sp.MsiPlicBridge` ([models/msi-plic-bridge.md](models/msi-plic-bridge.md)): what turns a PCIe device's interrupt messages into lines of the PLIC, one for each vector, as pulses. The host with a drive has it where M2's stand-in host has the MSI receiver.
- **A PLIC that hears a pulse**: five more items in the interrupt controller contract, and one more patch to the borrowed model, which forgot a pulse that came while its source was claimed.
- **Devicetree for PCIe**: the root complex and the bridge describe themselves, and `Platform.devicetree_overlay` writes the nodes of some components as an overlay. A component now describes its node once, with every port of it a bus master can reach.
- **In the Zephyr module**: a PCIe controller driver for the root complex, bindings for the two devices, and a shield, `socpuppet_host_drive`, whose overlay is generated from the host description. The board itself is still the host with no drive.
- **No change to the drive.** Zephyr's driver sends nothing the behavioral NVMe did not already answer.

Decided on 2026-10-08, planning M3b: **Zephyr's stock NVMe driver, with what it lacks supplied by socpuppet's Zephyr module**, and not a small NVMe driver of our own. Mainline Zephyr was checked first, as the plan said. It cannot deliver a message-signalled interrupt on RISC-V, and its NVMe driver has no polled mode. Five things in it had to be worked around, none of them by patching it, and each has an entry in [upstream.md](upstream.md). The exit firmware is Zephyr's own disk test, on the principle of borrowing before building.

What M2 delivered: a Python host that finds an NVMe drive over PCIe, enables it and reads and writes blocks, woken by MSI-X, with no CPU anywhere. The exit test is `tests/python/test_m2_exit.py`, on a host split over two dies, and `examples/nvme_hello.py` is the same show to run by hand.

- **The behavioral NVMe**, `sp.BehavioralNvme` ([models/behavioral-nvme.md](models/behavioral-nvme.md)): a controller that answers the host itself, as a plain C++ class with a thin SystemC wrapper. It is an NVMe function with no PCIe in it (a register block, a DMA port and one interrupt line per vector), which is the shape M4's SSD hardware will have. The layouts of its registers and commands are SPDK's.
- **The NVMe contract**, `tests/cpp/contracts/nvme_contract.h`: what every NVMe function must do, from enabling to block I/O, written from the specification with a test-side host of its own. M4's SSD is held to the same suite.
- **PCIe, our own**: a root complex ([models/pcie-root-complex.md](models/pcie-root-complex.md)) and an endpoint ([models/pcie-endpoint.md](models/pcie-endpoint.md)) that wraps any function, with configuration space, one 64-bit BAR and MSI-X. The link between them is a pair of plain TLM sockets, so it can be traced and can cross a die-to-die link.
- **Stand-ins for the host's side**: the MSI receiver ([models/msi-receiver.md](models/msi-receiver.md)), which turns an interrupt message into a wire, and in Python the PCIe host ([models/pcie-host.md](models/pcie-host.md)) and the NVMe driver ([models/nvme-host.md](models/nvme-host.md)), which M4's SSD kit will use as its host.
- **Under them**: a router that takes several masters (`bus.add_input()`), scripts that read and write runs of bytes (`sp.read`, `sp.write`), `platform.peek`, wire outputs that may be left unconnected, and components that work out a parameter from where they are in the description.

Decided on 2026-10-05, at M2's gate: **socpuppet writes its own PCIe endpoint**, and VCML stays out of the build. The spike that M2 planned is in [pcie-spike.md](pcie-spike.md). VCML's PCI endpoint works behind an adapter, from Python too, but the part of it that fits the design is small, the adapter is two thirds the size of the thing it replaces, and VCML ends the process with `abort()` on an error. The root complex was always going to be ours, because VCML's own PCI sockets cannot be a platform port, be traced, or cross a link. That settles the modeling-library question this plan had left open until M2: SCC for the router and logging, borrowed models where they fit behind an adapter, and no second framework.

What M1 delivered: [iss-spike.md](iss-spike.md), the report. Five CPU models were built and run behind a draft CPU slot (DBT-RISE-RISCV, QBox, riscv-vp, a prototype of our own, and riscv-vp-plusplus, which stopped at the build step on macOS), and VCML was probed as a library of peripheral models. Four of them boot stock Zephyr `hello_world` for RV64 and RV32. M3a rebuilt the DBT-RISE-RISCV wrapper test-first and then cleared `spikes/iss/`, leaving only QBox's recipe. The report names the last commit that held each of the others. The spike also set `Memory` to advertise DMI and the tracer to withhold it, test-first, because CPU models wait for that hint.

Decided on 2026-10-04, at M1's gate: **DBT-RISE-RISCV is the default CPU**, the one that ships in the wheel. socpuppet stays MIT, and the rule about GPL code becomes "none in the default wheel", so QBox, which is QEMU underneath, may be an optional CPU that users build from source (see the to-do list). The modeling library and the Zephyr pin were left open, with the report's recommendations as their defaults.

Decided on 2026-10-04, planning M3a:

- **Zephyr is pinned at 4.4.2 with SDK 1.0.1.**
- **Borrow before building.** Using existing open source matters as much as the teaching goal. Where an open model fits, socpuppet uses it behind an adapter and holds it to a contract suite, and where it falls short the first answer is to fix it, not to write our own. This replaces the M1 report's "thin layer of our own" as the default. For M3a the UART, the machine timer and the PLIC come from VPV-Peripherals, and ELF parsing from ELFIO.
- **Upstreaming is for later, and written down now.** Every patch and workaround to someone else's code has an entry in [upstream.md](upstream.md), with enough context to send it from there.
- **cibuildwheel is in M3a, publishing is not.**
- **Only `spikes/iss/qbox/` is left now that M3a has finished.** The spike's DBT-RISE-RISCV wrapper, riscv-vp, the in-house prototype and the VCML probe are deleted, and so are the `spike` preset and its CI job (see [iss-spike.md](iss-spike.md)).

What M3a delivered: the CPU kit. `host()` in `socpuppet.boards` is a RISC-V host built as two dies, and stock Zephyr boots on it from Python: `hello_world` prints `Hello World! socpuppet_host/socpuppet_rv64`, and `synchronization` has two threads taking turns 600 ms of simulated time apart, which takes the machine timer, its interrupt and the scheduler. Both are in CI, on Ubuntu and macOS, from the build tree and from the installed wheel. See [boot-your-firmware.md](boot-your-firmware.md).

- **The CPU**: DBT-RISE-RISCV as `dbt_rise_cpu`, 64- or 32-bit, linked statically into the wheel, with DMI, temporal decoupling and a GDB server ([models/dbt-rise-cpu.md](models/dbt-rise-cpu.md)). It took seven patches, two of them to its engine.
- **Three borrowed peripherals**, from VPV-Peripherals: `ns16550`, `machine_timer` and `plic`, each behind an adapter of ours and held to a contract suite written first.
- **Around them**: the CPU slot and the bus-master contract that the scripted master and the CPU both pass, the platform's quantum, an ELF loader (ELFIO), devicetree generation for a whole board, the Zephyr module with board `socpuppet_host` shipped inside the package (`socpuppet zephyr-module`), and portable wheels built and tested by cibuildwheel for Linux x86-64, Linux aarch64 and macOS arm64. Nothing is published yet.

What was measured, on an Apple silicon laptop unless it says otherwise:

- **The quantum.** A counted loop runs at 8.8 million instructions a second with a quantum of zero and 44 million with 100 µs, which is the default. Three seconds of simulated `synchronization` take 0.22 s.
- **The wheel.** About 3 MB for Linux x86-64, CPU included. Building and testing the wheels for one platform took 15 to 21 minutes in CI, the longest job by far, because each of the three wheels compiled every dependency again. Since the cleanup pass a compiler cache carries them from one wheel to the next and from one run to the next: 11 to 13 minutes on Linux with nothing cached, and 5 on macOS once the cache is there.
- **What borrowing three peripherals cost.** Four patches to VPV-Peripherals, 99 lines in all, every one a fault its contract suite found: a compare value written at time zero was ignored, the PLIC read past the end of an array for its last source, did not look again when its registers were written, and treated every source as edge-triggered. Three more things are worked around in the adapters without a patch: registers that are indeterminate until reset is pulsed, a header that does not include what it uses, and CMake targets that link all of SCC, so only the sources are fetched. The adapters are about 400 lines together. No model had to be given up on. Each item is in [upstream.md](upstream.md).

What M0 delivered: the build (SystemC and SCC from source, CI on Ubuntu and macOS, a devcontainer, a self-contained wheel tested with uv and pip), composing a platform by name through a registry, the Python description layer with devicetree and JSON output, `Memory`, the SCC router, the pass-through link as a pair of endpoints, wires for interrupt and reset, the scripted bus master (C++ coroutine and Python generator), the tracer, and contract suites for the memory and link slots. See [architecture.md](architecture.md).

Added after M0, before any more models: code-quality checks for every language in the tree, enforced in CI. C++ follows Google style (clang-format, cpplint, clang-tidy, warnings as errors), Python is formatted and linted by ruff and type-checked by mypy, Markdown is linted by rumdl, and there are coverage and sanitizer builds. See [style.md](style.md).

Left out of M0 on purpose, because nothing in M0 could exercise them. Each belongs to the milestone named:

| Item from the M0 list | Where it goes | Why |
|---|---|---|
| "Resolved" JSON dump after build | done in M2, without a second dump | `to_json()` includes what a component works out from the description (the root complex is the first: where its memory window is). It is the same before and after build. |
| Parameter schemas and fidelity tiers in the registry | when a model needs a parameter that is not a number | Parameters are plain name → number so far, checked by a catalogue parity test and by the factory's own ranges. A tier turned out to need no mechanism: planning M4, it is a choice between two description functions in Python. |
| Driving wires from Python | M5 | The scripted IO-die manager is the first thing that needs to release a reset from Python. |

Things later milestones should know:

- **A PCIe device's interrupts reach the host's CPU as pulses on PLIC sources.** The MSI-to-PLIC bridge has a line for each vector and nothing acknowledges it, so the line only pulses and the PLIC does the remembering. The interrupt controller contract holds a PLIC to that: a pulse is latched until claimed, and one that comes while the source is claimed is pending again at completion. A second device on the link would need vectors of its own on the bridge, and Zephyr's driver for the root complex (`socpuppet_pcie.c`) gives every device vector N on line N.
- **Firmware for the host with a drive is the board plus a shield.** `socpuppet_host` is the host with no drive, and its devicetree is checked in and held to the description by a test. So is the shield's overlay, `drive_overlay()` in `boards/host.py`. M4's SSD board is a board of its own, `socpuppet_ssd`, which is why the shield is not called that.
- **Zephyr's PCIe code is single-controller and was written for x86 and Arm.** What had to be worked around for a RISC-V host with a PLIC is in [upstream.md](upstream.md) under Zephyr. M6's two firmware images build on the same module.
- **The PCIe endpoint has MSI-X and nothing else in its capability list.** A driver that insists on the PCI Express capability, or on power management, will not find it. Zephyr's NVMe driver reads neither.
- **Nothing on the PCIe link says which device sent an access.** The link's extension marks configuration accesses and that is all.
- **An interrupt line of an NVMe function falls and rises again.** It is high while a completion is unacknowledged, an acknowledgement makes it fall, and it rises again a delta cycle later if completions remain. That is so that a PCIe endpoint can turn each rise into one MSI-X message without losing any. M4's SSD hardware has to do the same, and the contract suite checks it. The two halves are there to reuse: `InterruptRequests` (`core/interrupt_requests.h`) is what the controller's logic answers, and `InterruptLines` (`models/interrupt_lines.h`) turns it into lines from one process.
- **The NVMe contract's host waits up to 5 s of simulated time for a command and expects an acknowledged line to be low 1 ms later.** The first is Zephyr's default request timeout. An SSD whose firmware is slower than that fails the suite.
- **A trace record does not say which device an access came from, or whether it was a configuration or a memory access.** M7's exit test wants to see every NVMe command, DMA and MSI cross the die-to-die link, and is the first to need either. Until then a test tells them apart by address.
- **A script's access that the bus refuses stops the run with `BusError`**, naming the master, the address and TLM's response. A read of nothing no longer returns zeros. `sp.NvmeHost` and `sp.PcieHost` check what the protocol lets them (a completion that is not there, a status that is not success, a BAR that did not take its address) on top of that.
- A traced connection refuses DMI. Do not trace a CPU's path to its main memory and expect speed.
- The router takes several masters since M2 (`bus.add_input()`), all with one address map. A master that needs a different view of memory needs a router of its own.
- `Platform.build()` finishes SystemC elaboration through a kernel call (`sc_simcontext::initialize`) that is public in the reference kernel but not in the SystemC standard.
- SCC is built with two small patches and three other accommodations (see `cmake/Dependencies.cmake`). Each is written up in [upstream.md](upstream.md), ready to offer upstream.
- **One GDB server per process.** DBT-RISE keeps its server in a process-wide singleton, so a second `gdb_port` is refused with the reason. M6 wants two GDB ports, and that needs a change in DBT-RISE-Core first ([upstream.md](upstream.md)).
- **A CPU sees an interrupt up to one quantum late.** That is temporal decoupling and not a fault, but a test that times an interrupt has to allow for it. M6's "quantum tuning with two ISSs" starts from the figures above.
- **A handler that quiets its device is entered once**, because of a patch to DBT-RISE's SystemC wrapper: after a bus access the core yields for up to two delta cycles, so that a line the access lowered is seen low. A device that takes longer than that to lower its line will be seen as still asking.
- **Both bus masters give the platform a turn after every access**, of up to two delta cycles, so that a line the access lowered is seen low before the next access. The CPU does it by the DBT-RISE patch above, and the scripted master in `LetTheAccessTakeEffect`. The bus-master contract holds both to it with a script that claims, quiets and completes at a PLIC. A device that takes longer than two delta cycles to lower its line is seen as still asking, by either.
- **A CPU going to sleep does not let the clock catch up first.** DBT-RISE enters `wfi` without synchronizing, so the core can fall asleep up to a quantum ahead of simulated time. The bus-master contract's clock catch-up item is held by the scripted master only, and the limitation is in [upstream.md](upstream.md).
- **The borrowed timer and PLIC are reset by their adapters** at the start of simulation, because their registers hold whatever was in memory until reset is pulsed. A new adapter around a VPV-Peripherals model needs the same.
- **Every model on the NVMe path answers a debug access**, the debugger's kind that takes no simulated time: the root complex's two windows and its way up, the endpoint, the behavioral NVMe's registers, the MSI receiver and the MSI-to-PLIC bridge. So `platform.peek` and GDB see a drive's registers through the root complex. A debug write lands in a register and starts nothing. M4's SSD hardware is held to the same by the NVMe contract.
- **A device on the SSD's own bus shows its registers to a debugger and declines a debugger's write.** The flash controller is the first, and the DMA engine and the CPU's side of the NVMe frontend follow it. A command given by a debugger would be work the firmware never asked for. The host's side of the frontend is an NVMe function's register block, and is held to the NVMe contract's rule instead: a debug write lands and starts nothing.
- **A device that works for the SSD's CPU does the work in a process of its own, in the delta cycle after the CPU's write.** In that delta the CPU's process and the device's run in either order, so a master that waits one delta cycle and looks may or may not find the work done. Firmware polls a busy bit or takes the interrupt, and a test that polls does the same.
- **A host's reset of the SSD is a handshake between the frontend and the firmware.** The frontend drops its queues and the waiting command at once, and takes back "ready". Until the firmware acknowledges, by writing a one to the status bit that told it, the frontend fetches nothing and drops what the firmware still does about the old controller. The acknowledgement is a promise that the firmware holds nothing from before, so a driver makes it from where it does its work, and not from an interrupt handler. [The frontend's page](models/nvme-frontend.md) has the picture.
- **The glue between a socket and a register block exists four times**: in the shell of the two command devices, in the stand-in drive, and twice in the frontend. A review said a small class that owns the socket would name the debugger's policy once. It was left, because it changes no behaviour and M4 adds no fifth.
- **The flash controller knows the NAND's geometry only once it has been told to identify the chip.** Its geometry registers read as zero until then, and a page cannot be moved. Firmware identifies first.
- **A function's DMA and an endpoint's interrupt messages take no simulated time.** The behavioral NVMe and the PCIe endpoint send their accesses with no lead and drop whatever latency the target adds, because nothing on the host's side has a latency yet. The first host memory that takes time (M4's SSD buffer, or a slow DRAM) is where to start honouring it, with a contract item that sees a completion arrive no sooner than its DMA took.
- **A component's parameters are checked when it is created.** A factory reads them through `Parameters` (`platform/registry.h`), which refuses a parameter the factory never asked for and a value outside the range the factory gives. So a misspelled keyword on a Python component fails at `build()` with the names the implementation does take. A new factory gets this by asking for each parameter with its range.
- **A failed `build()` spends the process too.** When a module is destroyed before elaboration, SystemC hands its processes to the kernel and keeps them, so a second build would run them on modules that are gone. The kernel claim in `bindings/core.cpp` therefore stays taken, and the next `build()` says that an earlier one failed part-way. What can be done about it is to catch more in Python, before the simulator is created.
- **A wire takes one driver.** A component writes each of its wire outputs from one process of its own, whatever makes the line change, and the platform's signals check it (`SC_ONE_WRITER`). The behavioral NVMe, the MSI receiver, the MSI-to-PLIC bridge and the two borrowed adapters all keep one method for the job. A model that writes a line from the caller's thread in a register access and from a method of its own is stopped by SystemC at the first change from the second process, naming both.
- **A timer compare far in the future is safe.** `sc_time` ends at about 213 days and Zephyr's idle arms `mtimecmp` about 186 days ahead. The contract suite covers a compare value too far off to ever come.
- **The interpreter is the only DBT-RISE backend in the build.** Every core upstream generates is compiled along with the two socpuppet uses, because the library is built by upstream's own CMake.
- `Platform` is one class for both the description and the built simulation (`platform.build()`, then `platform.run()`). Splitting off a separate simulation object was considered and turned down: a process can only ever hold one simulation, so the two objects would always travel as a pair, and one object is easier to learn. The cost is a few "built yet?" checks, which are tested.

Between M3a and M3b: a cleanup pass, so that M3b builds on what the first three milestones learned and not on their first drafts. It fixed the two known bugs below, made errors that were swallowed come out (a refused bus access, a failed DMA, an interrupt message nobody answers, a parameter nobody asked for), gave the debugger a way to the drive's registers, and took apart what had grown too large to change safely: the platform builder, the builtin registry, the endpoint's registers, the NVMe controller's drive, the Python catalogue and the tests' support code. `host(drive_blocks=...)` is the board M3b starts from.

Left out of that pass on purpose. Each belongs to the milestone named:

| Left out | Where it goes | Why |
|---|---|---|
| More NVMe admin commands (Get Features, the two Delete Queue commands, Get Log Page), the capability fields nobody reads yet, shutdown | when a driver sends one | Zephyr's driver, the one M3b runs, sends none of them. |
| The UART's interrupt | when a console wants it | Zephyr's console is polled, and M3b needed none. |
| Who sent a packet on the PCIe link, and trace records that name the sender | M5 and M7 | One device on the link so far. |
| `cpu@N` from the CPU's index in a devicetree | M6 | A devicetree is one master's view, and there is one CPU in it until two firmware images run together. |
| The CPU's clock as a parameter (it is 10 MHz) | when a second CPU needs another | Nothing reads it but the CPU. |
| Typed results from script steps (a step may send back anything) | when an operation needs it | It would make every operation a class of its own. |
| Checking which vector woke `NvmeHost`, and how many queues it was granted | when a stand-in host uses more than vector 0 | The interrupt hook does not say which vector, and one queue pair is always granted. |
| mypy over the tests, the tools and the examples | not planned | The package is typed. The examples are run as tests, and annotating them would make a newcomer's first script harder to read. |
| Giving the kernel back after a failed `build()` | cannot be done | SystemC keeps the processes of destroyed modules (see the list above). |

## To do

Small things that are nobody's milestone. Tick them off or delete them.

- [ ] Reserve the `socpuppet` name on PyPI (free as of 2026-10-04; needs Chris's PyPI account). Do it before the first wheels are published. M3 is done, so nothing but the name stands in the way.
- [ ] Send the fixes and accommodations we carry to the projects they belong to: SCC, CCI, DBT-RISE-Core, DBT-RISE-RISCV, softvector, VPV-Peripherals, SPDK and VCML so far. Each has an entry in [upstream.md](upstream.md) with what is wrong, how to see it and what to propose.
- [ ] Run the C++ NVMe contract against the SSD with its Zephyr firmware. The rig `SsdRig` in `tests/cpp/contracts/nvme_test.cpp` has a C++ stand-in where the CPU goes. A second rig wants the CPU kit and the ELF loader, which the registry has, and the firmware image, which CI's C++ tests are not given today. Until then the firmware's share of the contract is held by `tests/python/test_ssd_firmware.py`.
- [ ] Enable QBox as an optional CPU. It is about ten times faster than the default and is QEMU underneath (GPL-2.0), so users build it from source and it is never in the wheel. The recipe and a wrapper that passes the spike's CPU suite are in `spikes/iss/qbox/`, which nothing builds automatically ([its README](../spikes/iss/README.md) has the commands). What is left: the timer interrupt input that `CpuSlot` has gained since, and a pass through the bus-master contract suite (`tests/cpp/contracts/bus_master_contract.h`), which is what a CPU is held to now; a supported way to build it outside that container (it wants its own SystemC as a shared library, a C++20 build that takes two patches, and about a dozen system packages); a registry entry and a Python class so that a platform can name it; macOS, which was not tried; its sleeping CPU, which keeps the kernel waiting so that `Platform.run()` with no time limit never returns; and a page saying what it is and what it costs. See [iss-spike.md](iss-spike.md).
- [ ] Try DBT-RISE-RISCV's other backends. The spike built only its interpreter (31 to 44 million instructions a second on a counted loop). asmjit, LLVM and TinyCC translate blocks of guest code into host code and should be faster. For each: run the bus-master contract suite and the CPU tests (`tests/cpp/platform/cpu_test.cpp`), measure a counted loop against the interpreter's 44 million instructions a second, and write down what it adds to the build and to the wheel. TinyCC is LGPL, so settle whether it may ship before turning it on. On macOS the helper the backends share declares a function called `wait()`, which collides with POSIX: the build leaves that file out, and a backend needs it back ([upstream.md](upstream.md)).

## Known bugs

Things that are wrong now and have no milestone. Tick them off or delete them.

- [x] **A script was woken twice per interrupt when its device was behind a PLIC.** Fixed: the scripted master lets each access take effect, for up to two delta cycles, as the CPU does, and the bus-master contract holds both to "claim, quiet and complete at a PLIC, interrupted once per interrupt".
- [x] **The PLIC adapter stopped the simulation with "conflicting write" when a source rose in the same delta cycle as a write to one of its registers.** Fixed: the adapter is now the only writer of `irq`, by a contract item that puts a rising line and an enable write in one delta cycle. The borrowed model's habit of writing its output from the caller's thread is in [upstream.md](upstream.md).
