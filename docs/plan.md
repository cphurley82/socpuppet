# socpuppet — high-level plan (milestones and tasks)

## Context

`docs/handoff-socpuppet.md` specifies an open-source SystemC/TLM virtual platform: a chiplet host (RV64 compute die, plus an IO die with an RV32 management core, joined by a UCIe-style D2D link) and an NVMe SSD (RV32 controller). Each runs its own Zephyr firmware inside one simulation that is composed and driven from Python. The repo holds only that brief, a README and a LICENSE.

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

```
M0 ─┬─ M1 (ISS gate) ── M3 host ──────────────┐
    ├─ M2 (PCIe + behavioral NVMe) ── M4 SSD ─┼─ M6 ── M7 ── M8 ── M10
    └─ M5 IO manager (5a link, 5b firmware) ──┘       M9 NAND: any time after M4
```

M3, M4 and M5 are independent of each other apart from the shared CPU kit, so they can run in parallel or in any order. Suggested serial order: M3, M4, M5.

## Phase 1: Foundation

**M0 — Scaffold + stand-in infrastructure**
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

**M1 — ISS spike (time-boxed; M2 does not wait on it)**
- Compare riscv-vp's ISS, a VCML-based approach and a minimal in-house ISS behind the CPU slot interface, on the handoff's criteria (in-process, LT + DMI, boots Zephyr, license, C++20, build simplicity).
- Report with a recommendation, and stop for a decision before any CPU-based model is built. The same report settles VCML vs. a thin in-house layer and proposes the Zephyr version to pin.

**M2 — PCIe + behavioral NVMe, no CPUs**
- PCIe TLM extension (config/mem space, requester ID); root complex with ECAM window, MMIO window, inbound DMA and MSI-X as memory writes; endpoint config space, BARs, MSI-X table.
- Behavioral NVMe device: RAM-backed, plain C++ core with a thin SystemC wrapper.
- Python "host driver" stand-in, and the NVMe contract suite that every later NVMe implementation must pass.

## Phase 2: Each subsystem boots its firmware standalone

Every track delivers the same kit to its firmware team: a Python platform description with that subsystem at full fidelity and its neighbors as stand-ins, the Zephyr board, a sample app, a pytest boot test, UART capture and GDB attach, and a short "boot your firmware here" doc.

The kit arrives as a Python package, because that is how a firmware developer gets the model: from M3 on, `uv add socpuppet` (or `pip install socpuppet`) pulls a prebuilt wheel for Linux and macOS with no compiler needed. That means cibuildwheel, PyPI publishing and versioning land with M3, and the Zephyr boards must be reachable from the installed package. M0 keeps the road open by building the wheel in CI and testing it installed with both uv and pip.

**M3 — Host subsystem** (board `socpuppet_host`; SSD = behavioral NVMe, D2D = pass-through)
- a) CPU kit, built once and reused by M4 and M5: ISS wrapper (RV64 and RV32IMAC), ELF loader, DRAM, NS16550 UART with Python capture, machine timer, PLIC, GDB hook. Zephyr module and board with devicetree generated from the platform description. Exit: `hello_world`, `synchronization`.
- b) PCIe enumeration from Zephyr; resolve the MSI-X-on-RISC-V question (verify mainline, else an MSI bridge model plus Zephyr hooks, or a minimal in-repo NVMe driver). Exit: Zephyr NVMe block I/O against the behavioral device.

**M4 — SSD subsystem** (board `socpuppet_ssd`; host = Python host stand-in from M2, NAND = ideal)
- a) SSD hardware with a Python "firmware" stand-in in the CPU slot: NVMe frontend (config space, BAR0 registers and doorbells, MSI-X table, SQE fetch engine, DMA engine, completion poster), flash controller, ideal NAND. Exit: M2 host tests and NVMe contract tests pass.
- b) RV32IMAC CPU, SRAM, DRAM buffer, UART, timer. Exit: Zephyr `hello_world` on `socpuppet_ssd`.
- c) SSD firmware: admin path, PRP handling, page-mapped FTL. Exit: the same M2 tests pass against the firmware, with data checked against the behavioral device.

**M5 — IO-die manager subsystem** (board `socpuppet_iomgr`; compute die = scripted stand-in held in reset)
- a) D2D link model: one link module per die, link state machine (reset → training → active, error/retrain), configurable latency and bandwidth, sideband register channel, error injection hooks, compute-die reset control. D2D contract suite passed by both pass-through and full link. Manager slot filled by a Python script that trains the link over sideband.
- b) RV32IMAC management core, UART, timer; Zephyr link-training and reset-release firmware. Exit: firmware boots, trains the link, releases reset, and the compute-side stand-in then reaches IO-die MMIO across the link.

## Phase 3: Full bootchain

**M6 — Host firmware ↔ SSD firmware** (monolithic host, pass-through link)
- Two ELF images in one simulation, reset/ready sequencing (host waits on CSTS.RDY while SSD firmware boots), two UART captures, two GDB ports, quantum tuning with two ISSs.

**M7 — Chiplet split** (manager = the M5a script)
- Host description becomes compute die + IO die; PCIe root complex and UART move to the IO die; board `socpuppet_compute` generated from the same description; cross-die address windows.
- Host Zephyr application source stays unchanged, which is the reuse claim the project exists to show.

**M8 — Full bootchain**
- Sequence under test: power-on → IO manager boots → trains D2D → releases compute die → host Zephyr boots across the link → PCIe enumeration → NVMe enable against the SSD firmware → block I/O.
- Three-image co-debug walkthrough in the docs.

## Phase 4: Fidelity and validation

**M9 — Realistic NAND**: geometry, tR/tPROG/tBERS delays, erase-before-write, sparse or file-backed storage, bad-block and bit-error hooks, NAND contract suite; FTL gains garbage collection.

**M10 — Validation scenarios**: boot-sequencing variants and failures, link down/retrain during I/O, cross-die data integrity, bad blocks, power loss, IOPS/latency stats.

**M11 — Stretch**: Verilator RTL block behind a TLM-to-signal adapter; power/telemetry model on the IO die.

## Decisions deliberately left open

| Decision | Must be settled by | Default until then |
|---|---|---|
| ISS choice; how far to lean on a modeling library (SCC is in the build since M0; VCML is the other candidate) | End of M1 (gates M3) | SCC for the router and logging only |
| Zephyr version pin | M1 / M3a | latest release with the needed RISC-V drivers |
| Host MSI-X on RISC-V | M3b | verify mainline first |
| Single- vs. multi-core SSD controller | M4b | single core |
| D2D mainband protocol (raw memory-mapped vs. PCIe/CXL-like layer) | M5a | raw memory-mapped transactions |
| Does "bootchain" include a ROM/bootloader stage per image? (not in handoff; ELFs are loaded from Python) | After M8 | no bootloader |
| `native_sim` firmware tier | Optional, any time after M3 | not built |
| Second compute die; host DRAM on the IO die | After M8 | one compute die, DRAM on compute die |

## Verification

- Every milestone ends with the automated end-to-end test in its "Exit test" column, run in GitHub Actions on Ubuntu LTS.
- Every slot interface has one gtest contract suite; a stand-in and its full model both pass it before either is used in an integration milestone.
- Stand-in configurations from earlier milestones stay in CI, so the standalone kits from M3 to M5 keep working after M6 to M8 land.
- Model logic lives in plain C++ classes, unit-tested without the SystemC kernel.

## Status

M0 in progress.
