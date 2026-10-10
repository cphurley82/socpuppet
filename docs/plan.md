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

**Decided on 2026-10-09, planning M5.**

- **The link is UCIe-style, as close as public sources allow**, in its state machine, its register layout and its sideband message format, so that a trace of a boot reads like a sideband capture of a real part and what a learner sees here is recognisable elsewhere. The sources are the Hot Chips 2023 UCIe tutorial and Berkeley's open [uciedigital](https://github.com/ucb-bar/uciedigital) RTL, which carries the encodings and offsets. The spec itself is not used. This retires the handoff's "never copy register tables" line, which was written to keep the evaluation copy of the spec out of the repo and is kept to in a stronger form: nothing here comes from the spec at all. ⚠️ The docs say "UCIe-style, modelled from public sources, not compliant", and that is not modesty: whole layers are missing.
- **Mainband traffic is raw memory-mapped TLM**, which settles the open decision. The endpoint forwards the payload untouched, adds time, and refuses DMI, because every access on real hardware has to cross the link and be seen doing so. Debug accesses cross whatever the link's state, since a debugger looks at memory without disturbing it.
- **One endpoint class, two per link, symmetric.** `sp.D2dLink(latency_ns=, bytes_per_ns=, training_ns=)` places a `D2dLinkEndpoint` on each die. It keeps the pass-through's four mainband sockets and adds a `sideband` target (the die's register block), a second peer pair for the sideband so it can be traced apart from mainband, and optional `reset` and `irq` wire outputs.
- **UCIe's link training state machine**: RESET → SBINIT → MBINIT → MBTRAIN → LINKINIT → ACTIVE, with PHYRETRAIN and TRAINERROR. RESET is held at least 4 ms and a substate left unanswered for 8 ms ends in TRAINERROR, both UCIe's own figures. `training_ns` is SBINIT to ACTIVE, a quarter of it per state. Only ACTIVE carries mainband: at any other time a transaction is refused with a generic error and never delivered, which a script sees as a bus error and firmware as a bus fault.
- **UCIe's sideband packets**, a 64-bit header and 0, 32 or 64 bits of data, travelling over the sideband pair as one TLM write of the packet's bytes at address 0. A completion is a packet back, not a nested reply, so the trace shows a request and its completion as two records the way a capture would.
- **The register block is the UCIe Link DVSEC at a static address**, which is how UCIe reaches it on a part with no configuration space: the extended capability header, the vendor header (0xD2DE), Link Capability, Link Control (start training, retrain), Link Status (up, training, status changed, uncorrectable fatal), the notification control that enables the interrupt, a register locator pointing at a vendor-defined block of ours (the state code, the far die's reset, fault injection), and the Sideband Mailbox, which performs a register access against the other endpoint. **The manager releases the compute die by a mailbox write of 0 to the compute endpoint's reset register** — the sideband is up from power-on, so it is reachable before the link is.
- **Timing is loosely timed**: `latency_ns` once per crossing, plus the transaction's bytes at `bytes_per_ns`, with each direction serialized on its own. ⚠️ A Python test cannot see 20 ns in `platform.time` after one write, because the initiator folds the delay into its quantum. Measure through the trace, whose records carry the arrival time, or set `platform.quantum = 0`.
- **No wire crosses the link.** An interrupt or a reset is a message on the sideband or it stays on its die. That closes the question the pass-through's page left open. ⚠️ The host board still wires the IO die's timer to the compute die's CPU; M7 moves the timer where it belongs.
- **The manager's stand-in is a Python script**, 🎭 `sp.IoManager`, in the shape of `sp.SsdFirmware`: start training, sleep until the interrupt, read Link Status, release the compute die, and retrain if a fault takes the link down. The C++ contract rig trains with bus writes instead, so there is no C++ stand-in for it.
- **`LinkContract` becomes rig-based**, in `NvmeContract`'s shape, because the D2D link has to be trained before it carries anything and the pass-through has nothing to train. The six items stay word for word; what only the real link does is tested on the real link.
- **The board is `socpuppet.boards.io_manager`**, with the IO die's map mirroring the SSD's so that the SoC `socpuppet_rv32` is reused, the DVSEC at 0x1001_0000, and a scratch memory as the round trip's target. The compute die's window onto the IO die is an **identity map**: a router hands its target an offset from the window's base, and the IO die's bus holds absolute addresses, so the compute die reaches the IO die at the addresses the manager itself uses. M7 will want the same.
- **The CPU kit becomes shared** (`boards/cpu_kit.py`), lifted out of the SSD board in a refactor of its own, as M5b is the third board to want it.
- **One Zephyr driver, one node.** `socpuppet,ucie-link` is a driver of Zephyr's reset class, because releasing the other die is exactly what that class is for, with training as plain functions beside it. 🚧 If the reset class rubs the way the flash class did, the fallback is a function of our own and an entry in [upstream.md](upstream.md).

The steps, each one `/tdd` session:

| # | Step | Where the behaviour goes |
|---|---|---|
| M5a 1 | `LinkContract` becomes rig-based (no behaviour change) | `tests/cpp/contracts/link_contract.h` |
| M5a 2 | Sideband packets encode and decode | `core/ucie_sideband.h` |
| M5a 3 | Latency and bandwidth per direction | `core/link_channel.h` |
| M5a 4 | The training state machine, both ends | `core/ucie_link_state.h` |
| M5a 5 | The DVSEC registers and the mailbox | `core/ucie_link_registers.h`, `core/d2d_link_logic.h` |
| M5a 6 | The endpoint, its wires and the contract | `models/d2d_link.h` |
| M5a 7 | `sp.D2dLink`, and `platform.link(trace=)` | `components.py`, `platform.py` |
| M5a 8 | 🎭 The manager script and the trace decoder | `io_manager.py`, `ucie.py` |
| M5a 9 | The board and the M5a exit test | `boards/io_manager.py` |
| M5b 10 | The CPU kit leaves the SSD board (no behaviour change) | `boards/cpu_kit.py` |
| M5b 11 | A manager with a CPU, and its Zephyr board | `socpuppet_iomgr` |
| M5b 12 | The driver, the firmware and the M5 exit test | `drivers/d2d/`, `firmware/iomgr` |

Left for later: dropped and corrupted transactions are M10's error injection, not M5's, which injects a fault and nothing finer.

## Phase 3: Full bootchain

### M6 — Host firmware ↔ SSD firmware

(monolithic host, pass-through link)

- Two ELF images in one simulation, reset/ready sequencing (host waits on CSTS.RDY while SSD firmware boots), two UART captures, two GDB ports, quantum tuning with two ISSs.

**Decided on 2026-10-10, planning M6.**

- **The drive under the host is a function handed to `host()`.** `host(drive_blocks=4096, drive=add_ssd)` puts the real SSD where 🎭 the stand-in drive is, and `add_behavioral_drive` stays the default. The SSD's hardware with 🎭 a script for its firmware is `functools.partial(add_ssd, firmware=...)`. This is M4's "a fidelity tier is a choice between two description functions" carried up a level: no flag and no second board, and a tier nobody has thought of yet is a function somebody writes. `HostDrive.ssd` becomes one drive or the other.
- **The board, the shield and the host's image do not change.** Both drives say the same of themselves to a host: the same vendor and device numbers, two interrupt vectors, a BAR of the same size. So `socpuppet_host` with the shield `socpuppet_host_drive`, and the M3b image built for them, run against either. A test holds the shield's overlay to what the host with the SSD generates. This is the project's reuse claim in small, and M7 makes it again across a die boundary.
- **The exit test is Zephyr's disk test, unchanged, with the drive swapped.** It is the M3b exit test on the host with the SSD, run twice: with the script for the SSD's firmware, and with Zephyr. ⚠️ The milestone map says "data checked against the behavioral device", and M6 does not do that itself. Zephyr's test writes, reads back and compares. Comparing the SSD with the stand-in drive, write for write, is M4's exit test, and the data path it checks does not depend on who the host is.
- **Two GDB ports move to M8**, where the three-image co-debug walkthrough already is. M6 has one debugger a simulation, on either CPU: `host(gdb_port=)`, or `add_ssd` with a `gdb_port`. The reason is in the list below.
- **The quantum is measured, not tuned by guesswork.** The exit test is timed at 0, 10 µs, 100 µs and 1 ms, the figures are written down here, and the default of 100 µs changes only if they say it should.

What planning found:

- **The SSD fits under the host as it is.** `add_ssd` takes the place of `add_behavioral_drive` with no clash of names, addresses, PLIC sources or devicetree labels. Each CPU has a router of its own, and the SSD's parts land in the group `ssd` under the labels the checked-in `socpuppet_ssd.dts` already has, so the SSD's image loads unchanged too. M4's exit test already puts both drives on one scripted host.
- **Each CPU has a console already**, because what a UART printed is kept by the instance. With two bus masters the platform has to be told whose firmware an image is, `load_elf(image, via=)`, which is how the SSD board works today.
- **Ready sequencing is there by construction.** The frontend says `CAP.TO` is one second and remembers an enable that comes while its firmware is booting, and the firmware answers it from its loop. Zephyr's driver waits a second and a half for `CSTS.RDY`. The firmware's table costs half a microsecond a page: a quarter of a millisecond for the exit test's 2 MiB drive, and a quarter of a second for 2 GiB, the largest the firmware takes. So M6 builds no sequencing. It writes the test that shows it, at the slow end.
- ⚠️ **Two CPU kits have never run in one simulation.** Two bare cores of different widths have (`tests/cpp/platform/cpu_test.cpp`), but not two PLICs, two timers and two UARTs borrowed from VPV-Peripherals. Step 3 is the first time, and the adapters are the first place to look if it fails.
- **Two GDB ports are three changes to someone else's code and a design question of ours.** DBT-RISE-Core's server is one a process. DBT-RISE-RISCV's wrapper always asks for core 0's debug adapter, with a `FIXME` beside it. The target description a debugger is sent is kept in a static that every session shares, so a 64-bit core and a 32-bit one would be sent the same description. And a CPU stopped in a debugger spins on the simulation's one thread, so the other CPU stops with it. That last is the handoff's deterministic co-debug, and what it asks for is that both debuggers attach before either core runs. M8 needs all of it for three images, so it is done once, there. 📮 The findings go into [upstream.md](upstream.md) with M6's docs.
- **The quantum is one number a process.** SystemC's global quantum is set once at `build()` and both CPUs go by it, so "quantum tuning with two ISSs" cannot mean a quantum for each. What two CPUs add is that each command costs at least two quanta of simulated time that hardware would not: the SSD's CPU sees the frontend's line up to a quantum late, and the host's CPU sees the completion's interrupt up to a quantum late.
- ⚠️ **Zephyr's NVMe request timeout is not what its name says.** `nvme_cmd.c` starts a timer of `CONFIG_NVME_REQUEST_TIMEOUT` seconds, five, at a command, and never stops it. When it fires, it compares uptime in milliseconds against the same five, so any command that has been waiting more than 5 ms is timed out. The disk test is over in half a second and never meets it. M9's sustained writes will, and that is when it gets its entry in [upstream.md](upstream.md).
- **Two things this plan said were out of date**, and are corrected where they stand: that nothing had checked the CPU under a reset held from time zero (the bus-master contract does), and that a devicetree would want `cpu@N` once two images ran together (it does not).

The steps, each one `/tdd` session. Steps 2 and 4 may go green with no code beyond step 1's. The skill says to stop and report when a new test passes first time, and both stay as configurations CI runs.

| # | Step | Where the behaviour goes |
|---|---|---|
| M6 1 | `host(drive=)`: the host described with the real SSD. The overlay it wants is the shield's, and its SSD's CPU sees the devicetree `socpuppet_ssd` was generated from. [address-map.md](address-map.md) gains the interrupt lines of the host with the SSD, the first table with two PLICs in it | `boards/host.py`, `tools/address_map_docs.py`, `tests/python/test_host_board.py` |
| M6 2 | Zephyr's disk test passes on the host with the SSD's hardware and 🎭 the firmware script, host image unchanged | `tests/python/test_m6_exit.py` |
| M6 3 | **The exit test**: two ELF images, Zephyr on the host and Zephyr on the SSD. Zephyr's read and write tests pass, and each CPU prints on its own console | `tests/python/test_m6_exit.py` |
| M6 4 | Ready sequencing: under an SSD whose firmware takes a quarter of a second to come ready, a 2 GiB drive, the host still finds it and the tests pass | `tests/python/test_m6_exit.py` |
| M6 5 | The quantum: the exit test at 0, 10 µs, 100 µs and 1 ms, wall time and simulated time, three runs each. A measurement, not a `/tdd` step | this page |
| M6 6 | The show and the docs: `examples/host_and_ssd_hello.py` with both consoles, "The host with the SSD" in [boot-your-firmware.md](boot-your-firmware.md), [architecture.md](architecture.md), "What M6 delivered" here, and the GDB findings in [upstream.md](upstream.md) | docs, examples |

Left for later: two GDB ports are M8's. The request timeout's entry in [upstream.md](upstream.md) waits for the run that first meets it.

### M7 — Chiplet split

(manager = the M5a script)

- Host description becomes compute die + IO die; PCIe root complex and UART move to the IO die; board `socpuppet_compute` generated from the same description; cross-die address windows.
- Host Zephyr application source stays unchanged, which is the reuse claim the project exists to show.

### M8 — Full bootchain

- Sequence under test: power-on → IO manager boots → trains D2D → releases compute die → host Zephyr boots across the link → PCIe enumeration → NVMe enable against the SSD firmware → block I/O.
- Three-image co-debug walkthrough in the docs.
- A debugger on each CPU at once, which was M6's and moved here when M6 was planned. It needs changes in DBT-RISE-Core and DBT-RISE-RISCV ([upstream.md](upstream.md)), and a decision of ours about the order debuggers attach in.

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
| Does "bootchain" include a ROM/bootloader stage per image? (not in handoff; ELFs are loaded from Python) | After M8 | no bootloader |
| `native_sim` firmware tier | Optional, any time after M3 | not built |
| Second compute die; host DRAM on the IO die | After M8 | one compute die, DRAM on compute die |

## Verification

- Every milestone ends with the automated end-to-end test in its "Exit test" column, run in GitHub Actions on Ubuntu LTS.
- Every slot interface has one gtest contract suite; a stand-in and its full model both pass it before either is used in an integration milestone.
- Stand-in configurations from earlier milestones stay in CI, so the standalone kits from M3 to M5 keep working after M6 to M8 land.
- Model logic lives in plain C++ classes, unit-tested without the SystemC kernel. A borrowed model is the exception: it is tested through its contract suite, behind its adapter.

## Status

**M0 to M6 are done.** Every subsystem has booted its own firmware standalone, which was Phase 2, and the first two of them now run together: the host's firmware with the SSD's. M7 (the real host across the real link) is next.

What M6 delivered: two firmware images in one simulation. The exit test is `tests/python/test_m6_exit.py`: Zephyr's own disk test on the host's 64-bit CPU reads and writes an SSD whose 32-bit CPU runs the Zephyr firmware of `firmware/ssd`, each printing on its own console. It is M3b's exit test with the drive swapped, and it runs with 🎭 the firmware script in the SSD as well. `examples/host_and_ssd_hello.py` is the show to run by hand: both consoles as one story, each line with the time it was said. [boot-your-firmware.md](boot-your-firmware.md) has a section on running the two together.

- **`host(drive_blocks=4096, drive=add_ssd)`**: the host takes the function that describes its drive. With none it is 🎭 the stand-in drive, as before. A host given a drive and no size says what is missing.
- **Neither image was built again, and nothing was modelled or patched.** The host's image is M3b's and the SSD's is M4's. A test holds the shield's overlay to what the host with the SSD generates, and another holds the SSD's CPU's view under the host to the devicetree `socpuppet_ssd` was generated from.
- **[address-map.md](address-map.md) has the host with the SSD**: no new map, and the interrupt lines of both interrupt controllers side by side.
- **One debugger, on either CPU.** `tests/python/test_gdb.py` attaches to each of the two in turn.
- **The quantum was measured and stays at 100 µs.** The figures are below.

What M6 found:

- **It worked the first time, all of it.** Two CPU kits in one kernel, Zephyr's NVMe driver against the firmware's Identify, both consoles, the wait for a slow SSD: none of the risks planning listed came to anything, and steps 2 to 4 added tests and no code. That is M2's contract suite and M4's "one suite for two firmwares" paying out. ⚠️ It also means no M6 test was seen to fail before its code existed. Each was checked with a mutation instead: a firmware script that forgets where it put a page, an SSD with no image loaded, a host given the small drive where the test wants the slow one.
- **The host is not ready for its drive until 0.12 s**, whichever drive it has. Zephyr on the host takes that long to reach the point of enabling it. The SSD's firmware is ready 4 ms in with a 2 MiB drive. So with a small drive nobody waits for anybody, and "the host waits on `CSTS.RDY` while the SSD's firmware boots" only happens with a drive of about a gigabyte or more. The test of it uses 2 GiB, where the firmware is 0.27 s making its table and the host is kept waiting 0.15 s.
- **A debugger on the second CPU reaches the second CPU.** Planning read DBT-RISE-RISCV's "core 0" `FIXME` as a risk to that. With one debugger it is not, and a test holds it. What the `FIXME` does spoil is smaller, and is in [upstream.md](upstream.md): both cores add their `sysc` command to the one adapter.
- ⚠️ **The GDB tests had a race, and M6's new one lost it in CI.** A debugger that attaches before the simulation starts is shown registers from before the CPU's reset, because DBT-RISE answers a register read on the server's thread and not the simulation's. Every test of where a CPU is stopped had been winning that race since M3a. The first test to attach to the second of two CPUs lost it in one CI job and won it in the others, after passing locally. The tests' debugger now reads a byte of memory first, which the simulation's thread answers, and the fault is in [upstream.md](upstream.md). It was pushed red and fixed forward.
- **A CPU with no program is busy, not idle.** An SSD with no image loaded runs whatever its empty memory holds and logs a warning for every access that nothing answers. Under pytest that cost over two minutes of wall time for two seconds of simulated time, where the passing test takes a fifth of a second: nearly half of the plugin's five-minute limit.
- **The reviews changed step 1 three ways.** The host's drive was first typed as "one drive or the other", which made the docstring's own recipe, `board.drive.ssd.cpu.socket`, fail a type checker: `Host` is generic in its drive now, and `host(drive=add_ssd)` is known to have a CPU. `host(drive=add_ssd)` with no size silently gave a host with no drive. And `drive_overlay` had learned the SSD's NAND geometry to pick a size both drives take: it takes the board to write the overlay of instead.
- **`boards/host.py` cannot import `boards/ssd.py`**, because the SSD's board has a scripted host in it that takes its addresses from the real host. Being generic in the drive is also what lets the host name no drive but its default.

What M6 did not do, that the plan said or implied:

- ⚠️ **The data is not checked against the behavioral device**, which is what the milestone map's exit says. Zephyr's test writes, reads back and compares. The SSD against the stand-in drive, write for write, is M4's exit test, and planning decided that was the place for it.
- **Two GDB ports.** They are M8's, with what was found in [upstream.md](upstream.md).
- **A quantum for each CPU.** There is one a process. Nothing measured asks for two.
- ⚠️ **/tdd was followed by hand**, a step at a time. Both reviews ran on step 1, the test review on steps 2 to 4 together, and the design review on step 6.

Things M7 and M8 should know about two firmwares together:

- **Say whose.** With two bus masters `load_elf`, `peek32`, `devicetree` and `address_map` all need `via=`, and so do `socpuppet devicetree` and `socpuppet address-map` with `--via`. M7 adds no CPU. M8 adds the third.
- **Wait for lines, not for events, and allow for 0.12 s.** M8's boot-order test has the manager's 5 ms first, and then a host that says nothing until it has started its drive.
- **A hang is expensive** (above). Give a test of two CPUs a limit in simulated time that is close to what it needs.
- **Who said what, and when, is in an example and not in the package.** `examples/host_and_ssd_hello.py` reads two consoles a line at a time and stamps each line with the simulated time. M8's boot-order test wants the same of three. Move it into the package then, with tests, and do not copy it.
- **Zephyr's NVMe request timeout** is in the planning block under [M6](#m6--host-firmware--ssd-firmware): a host that is still sending commands five seconds after its first can meet it.

What was measured in M6, on an Apple silicon laptop: the exit test's run at four quanta, with a 2 MiB drive, from the start to Zephyr's verdict. Every figure came out the same three runs in three, to the tenth of a millisecond of simulated time, which is what one kernel for both CPUs buys.

| Quantum | Wall time, the SSD | Simulated time, the SSD | Wall time, 🎭 the stand-in drive | Simulated time, 🎭 the stand-in drive |
|---|---|---|---|---|
| 0 | 5.4 s | 579 ms | 4.4 s | 489 ms |
| 10 µs | 0.23 s | 580 ms | 0.19 s | 496 ms |
| 100 µs, the default | 0.18 s | 598 ms | 0.15 s | 512 ms |
| 1 ms | 0.17 s | 746 ms | 0.15 s | 653 ms |

- **The default stays at 100 µs.** It is thirty times faster than no quantum and stretches the run by 3%. 10 µs costs a quarter more wall time for that 3%, and 1 ms buys no wall time at all and stretches the run by 29%: the test still passes, a sixth of a second late.
- **A second CPU costs a fifth more wall time**, 0.18 s where one CPU takes 0.15 s. Both are asleep for most of the run, waiting for each other, so this is not a measure of two busy CPUs. M3a's counted loop is still the figure for that.
- **The SSD's firmware costs 87 ms of simulated time, whatever the quantum.** The disk test sends 69 commands, so that is 1.3 ms a command, which is what M4c measured with a scripted host.
- ⚠️ **What a longer quantum stretches is the host, not the pair.** Planning M6 expected two CPUs to cost two quanta a command, one for each interrupt seen late. The run grows by as much with 🎭 the stand-in drive, which has no CPU: 23 ms at 100 µs against the SSD's 19 ms. So the lateness is in the one CPU that both runs have, and a second CPU added nothing that grows with the quantum. Where in the host it goes was not chased. It is not a fixed number of quanta a command: with the stand-in drive the run grows by 6 ms at 10 µs, which is nine quanta for each of the 69, and by 164 ms at 1 ms, which is two and a half. A guess to start from is Zephyr's own timekeeping, against a timer interrupt that is itself up to a quantum late.

**Decided on 2026-10-09, after M5: one source for the hardware/software interface.** The maintainer asked why the address map, and everything else firmware and hardware have to agree on, was spread over the model with no one place to look. It was two problems. The address map had one source, each board's Python description, and no catalogue: it existed only while a devicetree was being written. The register maps had no source at all: each block's offsets and bits were written out by hand in the model, the Zephyr driver, the Python stand-in, the C++ test stand-in, the tests and the docs, four to eight times a block, and only the tests that boot firmware kept them in step.

- **The Python description stays the one place a platform is put together**, as [the handoff](handoff-socpuppet.md) decided. No chip-level file was added above the boards. What was added is a way to ask the description for its maps.
- **Register maps are written in SystemRDL**, one file a block in `regs/`, because it is the language the industry writes them in and a learner will meet it again. The compiler is borrowed, systemrdl-compiler (MIT), as a developer's tool. The three writers are ours: PeakRDL has exporters for C, Python and Markdown (LGPL, LGPL and GPL), and what was wanted was smaller and of a particular shape, a header of nothing but `#define` that C++ and Zephyr's C can share, a module of plain numbers, and one table row a register.
- **What is generated is checked in**, and lint fails while a generated file is not what its source gives, as the boards' devicetrees already were.
- **Only socpuppet's own blocks have a register map**: not the borrowed UART, timer and PLIC, and not what a specification lays out.

What it delivered. [architecture.md](architecture.md#where-the-hardwaresoftware-interface-is-written-down) has the picture, and [style.md](style.md#systemrdl) the conventions.

- **`Platform.address_map()` and `Platform.interrupt_map()`**: what answers at which address, to which bus master, through which windows, and whose interrupt line is which number. Both are in `Platform.to_json()`, and `socpuppet address-map` prints them, for people or as JSON, for every bus master or from any one port.
- **The tables in [address-map.md](address-map.md) are generated** from the boards by `tools/address_map_docs.py`, and the page gained each board's interrupt lines, the scripted host's map and the compute die's view of the IO manager board.
- **Five register maps**: the command device (what the DMA engine and the flash controller share), the DMA engine, the flash controller, the CPU's side of the NVMe frontend and the die-to-die link. `tools/regs.py` writes a C header, a Python module and the table on the block's page from each.
- **Every consumer goes by the generated names**: the models, the Zephyr drivers, both firmware stand-ins, the manager stand-in, the components' sizes and the tests. The C++ uses the macros where it used to keep constants of its own beside them, so one search finds everything that touches a register.
- **Cross-checks for what is not generated**: each compatible against its binding, its file name and its driver, and the interrupt numbers in Zephyr's Kconfig against the CPU's and the PLIC's.

What it found:

- **Moving a register is one edit now, and that was tried.** For each block the map alone was changed (registers swapped, bits moved, commands renumbered), everything regenerated, and the models, the firmware images and the whole suite built and run again. It took all four blocks to pass, and it found the copies nobody had listed.
- **The flash controller's model had a copy of how its commands are numbered**: it took a number for a command if it was between the first command's and the last's. It asks now whether it is one of the four.
- **Two Python tests had a status register written out**, offset and bits, to poke at a device that was not there.
- **[address-map.md](address-map.md) was wrong about the link's registers.** It said they could be reached from one die only. The generated table shows the IO die's end in the compute die's map as well, through the window.
- **clang-tidy would rather have enums than a C header's macros**, so the generated headers are excluded from its header checks, by name, in `.clang-tidy`.
- **A state called RESET and a register's value at reset nearly got one name.** The value is `_AT_RESET`, and `tools/regs.py` refuses a map in which two things would be called the same.

What it did not do:

- **The gaps a register map leaves reserved are still written by hand**, in the one test a block that names them and in a sentence under each table.
- **A sideband packet's layout is still in two places**, C++ and `socpuppet.ucie`, kept in step by the manager stand-in reading packets back out of a trace. It is a packet format and not a register map, and SystemRDL has nothing to say about it.
- **`build()` does not refuse an address map that loops**, where a router's output leads back to one of its own inputs. The maps and `to_json()` do. It is in the to-do list.
- ⚠️ **/tdd was followed by hand**, a step at a time, with its two reviews run on most steps and not on all: the four blocks after the first were the same pattern and were held by the mutation runs instead.

What M5b delivered, and with it M5: the IO die's manager runs its own firmware. The exit test is `tests/python/test_m5_exit.py`: Zephyr on the manager's CPU trains the link and lets the compute die go, the compute-side stand-in round-trips a word through the IO die's memory across the link, and when something faults the link the firmware trains it again and the dies carry on. [boot-your-firmware.md](boot-your-firmware.md) has a section on the board.

- **The board**, `socpuppet_iomgr`: the same RV32 core and kit as the SSD's controller, with the link's registers where the SSD has its frontend's, so both share the SoC `socpuppet_rv32`. Nothing new had to be modelled. The kit is `boards/cpu_kit.py` now, out of the SSD board.
- **One driver**, `socpuppet,ucie-link`, a driver of Zephyr's reset class. The other die is its one reset line, and letting it go is `reset_line_deassert()`. **The reset class fitted**, so the fallback the plan kept in reserve was not needed and there is nothing for [upstream.md](upstream.md).
- **The firmware**, `firmware/iomgr`: sixty lines. Train, release, then sleep until the link goes down and train it again.
- **Firmware that cannot do its job says why.** A link that will not train is a sentence on the console, and a test.

What M5b found:

- ⚠️ **The link's interrupt is a level, and the first driver hung on it.** The line is high while the status says it has changed, so a handler that only woke its thread was called again the moment it returned, for ever: Zephyr trained the link and never printed that it had. The handler clears the bit now. The 🎭 script never showed this, because a script has no handler to return from.
- **The compute die runs the instant it is released**, before the manager has finished saying it released it. A test that reads the console when the round trip lands reads half a line. M8's boot-order test across three UARTs has to wait for lines and not for events.
- **Asking for a driver class is the application's to do.** The driver first selected `RESET` by itself, which put it and the reset subsystem into `hello_world` for the board unasked. It depends on `RESET` now, as the flash driver depends on `FLASH`.
- **The driver is as small as the firmware needs.** The reset API has four operations and the driver has one, and the mailbox can read as well as write and the driver only writes. M8 can add what it wants.

Things M6 to M8 should know about the link:

- **A debugger's look crosses a link that is down**, and a transaction does not: it is refused with a generic error, which Zephyr sees as a bus fault with the address in `mtval`. M7's host must not touch the IO die before the manager has let it go, and cannot, because it is held in reset until then.
- **Serialization is by the order transactions are handed over**, which under temporal decoupling is not the order of their departure times ([models/d2d-link.md](models/d2d-link.md)).
- **The compute die's window is an identity map**, so M7's host reaches the IO die at the IO die's own addresses. The host board's window today translates, and the M3 devicetree was generated for it: M7 changes the host's map.
- **The DBT-RISE core honours a reset held from time zero.** This list said until 2026-10-10 that nothing had checked it, and planning M6 found that something had. The bus-master contract's `WhileResetIsHighTheMasterWaitsAndThenStarts` raises the reset as the simulation starts, and it is run against the CPU as well as the scripted master. A wire starts low and the link raises its reset in the first delta cycle, which is safe because the core waits two delta cycles before it first looks. M7 still wants a test of its own with the link holding the reset, but it does not start from a doubt.
- **The reset hold is 4 ms of every boot**, and the link's training is a millisecond more by default. M8's test waits at least 5 ms of simulated time before the host can run an instruction.

What M5a delivered: the real die-to-die link, and 🎭 a script in the manager's place that brings it up. The exit test is `tests/python/test_m5a_exit.py`: the manager trains the link and lets the compute die go, and the compute-side stand-in then round-trips a word through the IO die's memory across the link — and nothing of it crosses before the link has been trained. `examples/io_manager_hello.py` is the show to run by hand: it prints UCIe's whole bring-up, packet by packet, out of the trace.

- **The link**, [models/d2d-link.md](models/d2d-link.md): UCIe's training state machine, its Link DVSEC registers and its sideband message format, as far as public sources say what they are, with the timing of a crossing on top. 🎭 The pass-through stand-in stays, and both pass `LinkContract`.
- **Four plain classes behind it**, none of which needs a simulator: the sideband packet (`core/ucie_sideband.h`), the timing of one direction (`core/link_channel.h`), the state machine (`core/ucie_link_state.h`) and the registers (`core/ucie_link_registers.h`), composed by `core/d2d_link_logic.h`. The SystemC shell is 200 lines with one process in it.
- **UCIe in Python too**, `socpuppet.ucie`: the offsets the manager drives, and the packet format, so that a traced link reads back as a capture. The test that decodes a real run is also what keeps the Python register map and the C++ one in step.
- **🎭 The manager**, [models/io-manager.md](models/io-manager.md), and the board around it, `socpuppet.boards.io_manager`.
- **A link comes up in 5 ms** of simulated time by default: 4 ms of that is UCIe's reset hold, which a link cannot leave sooner, and the rest is the training time the model is given.

What planning M5a got wrong, or left to be found:

- **PHYRETRAIN is not modelled.** The decisions listed it among the states. A retrain here starts over from RESET, so a state for retraining in place had nothing to do and no test wanted one.
- **The mailbox is 32 bits wide, not 64.** The decisions gave it an address and data in halves. A sideband register access carries a 24-bit address and 32 bits of data, so the high halves could never have travelled.
- **Each end holds one channel, not two.** The end a transaction leaves is the only one that knows when it set off, so that is where its time is counted; the other end has nothing to add.
- **Two delta-cycle races, both in tests.** Firmware polling a status register sees the link up before the wire driven from it rises. `LineWatcher::WaitForLevel` and the manager's own interrupt-driven wait are how that is waited for properly. ⚠️ M5b's driver has the same trap.
- **A debugger cannot write the link's registers**, so a test cannot inject a fault with `poke32`. What does it is a script on the die, which is what firmware would be.

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
- **No register header shared by the models and the drivers.** The plan floated one C header for both. The drivers have their own definitions, a dozen lines each, and the tests that run firmware on the models are what keeps the two in step. 🦜 Reversed on 2026-10-09: there is one header a block now, generated from its register map (see "one source for the hardware/software interface" above).
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
| Driving wires from Python | nowhere; not needed | The scripted IO-die manager was expected to want it, and does not: planning M5 settled that no wire crosses the link, so the manager releases the compute die by writing a register over the sideband, as the firmware does. Python drives a wire by writing to the model that owns it. |

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
- **One GDB server per process.** DBT-RISE keeps its server in a process-wide singleton, so a second `gdb_port` is refused with the reason. Two GDB ports were M6's and are M8's since planning M6, which found that they need changes in DBT-RISE-RISCV as well as DBT-RISE-Core ([upstream.md](upstream.md)).
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
| `cpu@N` from the CPU's index in a devicetree | nowhere; not needed yet | A devicetree is one master's view. Planning M6 found that this holds with two firmware images in one simulation: the host's image and the SSD's each get a view with one CPU in it, and `cpu@0` is right in both. Two cores on one bus would be the first to want it. |
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
- [ ] Have `build()` refuse an address map that loops, as `Platform.address_map()` and `to_json()` do: a router with an output mapped onto one of its own inputs builds today, and an access into that range would go round for ever. The walk that finds it is `socpuppet.address_map`, and the test to write first is in `tests/python/test_platform.py`.
- [ ] 🚧 An idea, not a decision: write a board's hardware as data, and have Python load it. The maintainer asked on 2026-10-10 whether addresses and interrupt numbers could live in pure data files that Python reads and a devicetree is converted from, where today they are in each board's Python and the devicetree is made by walking that description. Moving the numbers alone would not do it: a devicetree also says what each device is and reaches it through the windows, so the file has to hold the devices, the buses, the links between dies and the interrupt lines, which makes it a platform description format and reverses the handoff's "platforms are described in Python only". How it would work: a TOML file a board (TOML has `0x8000_0000`, and Python reads it with `tomllib`), with `[components]` (path to class and parameters), `[links]` (model, and the two groups it joins), a `[buses."<path>"]` table a bus with its `masters` and a `map` of `{ at, size, to, across }` rows, and `[interrupts]` (input to line). A `Platform.load(file)` makes the same `add`, `map`, `connect` and `link` calls a board's Python makes now, so `build()`, the devicetree generator, `socpuppet address-map`, the docs tables and `to_json()` are untouched, C++ still never reads a description, and a platform written in Python still works. A variant is a second file laid over the first (`host_drive.toml` over `host.toml`, as Zephyr lays the shield over the board), and a shared piece (`cpu_kit`) is a file with relative names, loaded under a group. Python keeps the scripts, the options of a run (debugger port, drive size, tracing), the choice of files, and running the result; a stand-in or a test looks an address up in the loaded map where it imports a constant today. ⚠️ What gets awkward: a script in the CPU's place changes the hardware (no SRAM, UART, timer or PLIC, and the device's line goes straight to the script), so the SSD and the IO manager each split into the devices and the CPU with its interrupt numbers; four boards become about eight files; and files name each other's components, so a typo is found by the loader and its messages matter. The host converts cleanly and would read better as data; the SSD and the IO manager would likely be harder to follow than the one Python file each is. If it is tried, convert the host alone first, with its checked-in `.dts` unchanged as the proof that nothing moved, and decide the rest from how that reads. --- I'd also consider JSON and YAML in addition to TOML. I think a flow where Python generates JSON for the description and that JSON is read into either the simulaiton python or tools to generate device tree for firmware could be good. We could even have this description replace RDL. I still wouldn't want to loose the ability to do things in python alone without the conversion to/from json.
- [ ] Model an IOMMU on the IO die's CXL/PCIe root complex path: translation-table walks, protection and faults, with a contract suite written first (borrow before building: check for an open model to put behind an adapter before writing one).
- [ ] Model SHRM (CXL shared/host-managed device memory) on the IO die: an HDM decoder that resolves a fabric-shared range, plus a minimal fabric-manager stand-in that carves it up. Sits downstream of the IOMMU item above in the request path.
- [ ] Model RISC-V's AIA: IMSIC on the compute die (per-hart, receives MSIs), APLIC on the IO die (aggregates wired/device interrupts into MSIs for IMSIC). Likely replaces or sits alongside the PLIC once a milestone needs MSI-based interrupts instead of wired ones.

## Known bugs

Things that are wrong now and have no milestone. Tick them off or delete them.

- [x] **A script was woken twice per interrupt when its device was behind a PLIC.** Fixed: the scripted master lets each access take effect, for up to two delta cycles, as the CPU does, and the bus-master contract holds both to "claim, quiet and complete at a PLIC, interrupted once per interrupt".
- [x] **The PLIC adapter stopped the simulation with "conflicting write" when a source rose in the same delta cycle as a write to one of its registers.** Fixed: the adapter is now the only writer of `irq`, by a contract item that puts a rising line and an enable write in one delta cycle. The borrowed model's habit of writing its output from the caller's thread is in [upstream.md](upstream.md).
