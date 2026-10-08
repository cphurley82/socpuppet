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

- a) SSD hardware with a Python "firmware" stand-in in the CPU slot: NVMe frontend (config space, BAR0 registers and doorbells, MSI-X table, SQE fetch engine, DMA engine, completion poster), flash controller, ideal NAND. Exit: M2 host tests and NVMe contract tests pass.
- b) RV32IMAC CPU, SRAM, DRAM buffer, UART, timer. Exit: Zephyr `hello_world` on `socpuppet_ssd`.
- c) SSD firmware: admin path, PRP handling, page-mapped FTL. Exit: the same M2 tests pass against the firmware, with data checked against the behavioral device.

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
- Model logic lives in plain C++ classes, unit-tested without the SystemC kernel. A borrowed model is the exception: it is tested through its contract suite, behind its adapter.

## Status

**M0, M1, M2 and M3a are done.** M3b (Zephyr NVMe block I/O on the host) comes next, and has what it needs. M4 and M5 are independent of it.

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
- **The wheel.** About 3 MB for Linux x86-64, CPU included. Building and testing the wheels for one platform takes 15 to 21 minutes in CI, the longest job by far.
- **What borrowing three peripherals cost.** Four patches to VPV-Peripherals, 99 lines in all, every one a fault its contract suite found: a compare value written at time zero was ignored, the PLIC read past the end of an array for its last source, did not look again when its registers were written, and treated every source as edge-triggered. Three more things are worked around in the adapters without a patch: registers that are indeterminate until reset is pulsed, a header that does not include what it uses, and CMake targets that link all of SCC, so only the sources are fetched. The adapters are about 400 lines together. No model had to be given up on. Each item is in [upstream.md](upstream.md).

What M0 delivered: the build (SystemC and SCC from source, CI on Ubuntu and macOS, a devcontainer, a self-contained wheel tested with uv and pip), composing a platform by name through a registry, the Python description layer with devicetree and JSON output, `Memory`, the SCC router, the pass-through link as a pair of endpoints, wires for interrupt and reset, the scripted bus master (C++ coroutine and Python generator), the tracer, and contract suites for the memory and link slots. See [architecture.md](architecture.md).

Added after M0, before any more models: code-quality checks for every language in the tree, enforced in CI. C++ follows Google style (clang-format, cpplint, clang-tidy, warnings as errors), Python is formatted and linted by ruff and type-checked by mypy, Markdown is linted by rumdl, and there are coverage and sanitizer builds. See [style.md](style.md).

Left out of M0 on purpose, because nothing in M0 could exercise them. Each belongs to the milestone named:

| Item from the M0 list | Where it goes | Why |
|---|---|---|
| "Resolved" JSON dump after build | done in M2, without a second dump | `to_json()` includes what a component works out from the description (the root complex is the first: where its memory window is). It is the same before and after build. |
| Parameter schemas and fidelity tiers in the registry | M4 | Parameters are plain name → number so far, checked by a catalogue parity test, and M2's models needed nothing more. A tier is a choice between implementations of one slot, and M4's SSD is the first second implementation. |
| Driving wires from Python | M5 | The scripted IO-die manager is the first thing that needs to release a reset from Python. |

Things later milestones should know:

- **M3b starts from a host with no path for MSI.** The MSI receiver is a stand-in with a register of its own invention. Zephyr's NVMe driver wants MSI-X, and on RISC-V that means an IMSIC or a bridge to the PLIC, and Zephyr hooks that mainline does not have. That is M3b's open question, unchanged.
- **The PCIe endpoint has MSI-X and nothing else in its capability list.** A driver that insists on the PCI Express capability, or on power management, will not find it. Zephyr's is not known to. Add what M3b's driver turns out to read.
- **Nothing on the PCIe link says which device sent an access.** The link's extension marks configuration accesses and that is all.
- **An interrupt line of an NVMe function falls and rises again.** It is high while a completion is unacknowledged, an acknowledgement makes it fall, and it rises again a delta cycle later if completions remain. That is so that a PCIe endpoint can turn each rise into one MSI-X message without losing any. M4's SSD hardware has to do the same, and the contract suite checks it.
- **The NVMe contract's host waits up to 5 s of simulated time for a command and expects an acknowledged line to be low 1 ms later.** The first is Zephyr's default request timeout. An SSD whose firmware is slower than that fails the suite.
- **A trace record does not say which device an access came from, or whether it was a configuration or a memory access.** M7's exit test wants to see every NVMe command, DMA and MSI cross the die-to-die link, and is the first to need either. Until then a test tells them apart by address.
- **The scripts' bus accesses still ignore the response status.** A read of nothing returns zeros. `sp.NvmeHost` and `sp.PcieHost` check what they can (a completion that is not there, a status that is not success, a BAR that did not take its address).
- A traced connection refuses DMI. Do not trace a CPU's path to its main memory and expect speed.
- The router takes several masters since M2 (`bus.add_input()`), all with one address map. A master that needs a different view of memory needs a router of its own.
- `Platform.build()` finishes SystemC elaboration through a kernel call (`sc_simcontext::initialize`) that is public in the reference kernel but not in the SystemC standard.
- SCC is built with two small patches and three other accommodations (see `cmake/Dependencies.cmake`). Each is written up in [upstream.md](upstream.md), ready to offer upstream.
- **One GDB server per process.** DBT-RISE keeps its server in a process-wide singleton, so a second `gdb_port` is refused with the reason. M6 wants two GDB ports, and that needs a change in DBT-RISE-Core first ([upstream.md](upstream.md)).
- **A CPU sees an interrupt up to one quantum late.** That is temporal decoupling and not a fault, but a test that times an interrupt has to allow for it. M6's "quantum tuning with two ISSs" starts from the figures above.
- **A handler that quiets its device is entered once**, because of a patch to DBT-RISE's SystemC wrapper: after a bus access the core yields for up to two delta cycles, so that a line the access lowered is seen low. A device that takes longer than that to lower its line will be seen as still asking.
- **The scripted master only sees a quieted device as quiet when it is wired straight to `irq`.** It lets one delta cycle pass before it waits for an interrupt, and no more. With a PLIC in between, a script that claims, quiets and completes is interrupted twice per interrupt, because its accesses run back to back. The CPU yields after each access. Giving the stand-in the same rule is a contract item waiting for the first platform that puts a controller in front of it. This is a known bug, at the end of this page.
- **A CPU going to sleep does not let the clock catch up first.** DBT-RISE enters `wfi` without synchronizing, so the core can fall asleep up to a quantum ahead of simulated time. The bus-master contract's clock catch-up item is held by the scripted master only, and the limitation is in [upstream.md](upstream.md).
- **The borrowed timer and PLIC are reset by their adapters** at the start of simulation, because their registers hold whatever was in memory until reset is pulsed. A new adapter around a VPV-Peripherals model needs the same.
- **A timer compare far in the future is safe.** `sc_time` ends at about 213 days and Zephyr's idle arms `mtimecmp` about 186 days ahead. The contract suite covers a compare value too far off to ever come.
- **The interpreter is the only DBT-RISE backend in the build.** Every core upstream generates is compiled along with the two socpuppet uses, because the library is built by upstream's own CMake.
- `Platform` is one class for both the description and the built simulation (`platform.build()`, then `platform.run()`). Splitting off a separate simulation object was considered and turned down: a process can only ever hold one simulation, so the two objects would always travel as a pair, and one object is easier to learn. The cost is a few "built yet?" checks, which are tested.

## To do

Small things that are nobody's milestone. Tick them off or delete them.

- [ ] Reserve the `socpuppet` name on PyPI (free as of 2026-10-04; needs Chris's PyPI account). Do it before the first wheels are published, which is M3b at the earliest.
- [ ] Send the fixes and accommodations we carry to the projects they belong to: SCC, CCI, DBT-RISE-Core, DBT-RISE-RISCV, softvector, VPV-Peripherals, SPDK and VCML so far. Each has an entry in [upstream.md](upstream.md) with what is wrong, how to see it and what to propose.
- [ ] Enable QBox as an optional CPU. It is about ten times faster than the default and is QEMU underneath (GPL-2.0), so users build it from source and it is never in the wheel. The recipe and a wrapper that passes the spike's CPU suite are in `spikes/iss/qbox/`, which nothing builds automatically ([its README](../spikes/iss/README.md) has the commands). What is left: the timer interrupt input that `CpuSlot` has gained since, and a pass through the bus-master contract suite (`tests/cpp/contracts/bus_master_contract.h`), which is what a CPU is held to now; a supported way to build it outside that container (it wants its own SystemC as a shared library, a C++20 build that takes two patches, and about a dozen system packages); a registry entry and a Python class so that a platform can name it; macOS, which was not tried; its sleeping CPU, which keeps the kernel waiting so that `Platform.run()` with no time limit never returns; and a page saying what it is and what it costs. See [iss-spike.md](iss-spike.md).
- [ ] Try DBT-RISE-RISCV's other backends. The spike built only its interpreter (31 to 44 million instructions a second on a counted loop). asmjit, LLVM and TinyCC translate blocks of guest code into host code and should be faster. For each: run the bus-master contract suite and the CPU tests (`tests/cpp/platform/cpu_test.cpp`), measure a counted loop against the interpreter's 44 million instructions a second, and write down what it adds to the build and to the wheel. TinyCC is LGPL, so settle whether it may ship before turning it on. On macOS the helper the backends share declares a function called `wait()`, which collides with POSIX: the build leaves that file out, and a backend needs it back ([upstream.md](upstream.md)).

## Known bugs

Things that are wrong now and have no milestone. Tick them off or delete them.

- [ ] **A script is woken twice per interrupt when its device is behind a PLIC.** To see it: a scripted master, a router, a `plic` and an interrupt source on `source1`, with a script that loops `wait_irq`, claim, quiet, complete. Wired straight to `irq` the device is quieted twice for two interrupts. Through the PLIC it is quieted four times, because the PLIC still reports the device as asking when the script completes the interrupt. The master lets one delta cycle pass in `WaitIrq` and nowhere else, and the real CPU yields after every access, by the DBT-RISE patch `cmake/patches/dbt-rise-riscv-interrupt-after-access.patch`. A fix that was measured: drop the wait from `WaitIrq` and, after each access, yield up to two delta cycles while anything is pending, as the CPU does. That gives two for two on both wirings, and the scripted master's and the bus-master contract's tests pass with it. It wants a failing test first: "a script that claims and completes at a PLIC is woken once per interrupt". The limit is written under "Things later milestones should know" and in [the scripted master's page](models/scripted-bus-master.md).
- [ ] **The PLIC adapter stops the simulation with "conflicting write" when a source rises in the same delta cycle as a write to one of its registers.** SystemC reports `E115`: the signal `irq` cannot have more than one driver, with "conflicting write in delta cycle 1" and a second driver `cpu.Run`. The adapter writes `irq` from its own method on an edge of a source and from the caller's thread on a register write, and SystemC allows one writer per delta cycle. It was seen when a device raised its line at time zero, in the same delta cycle as a script's write to the PLIC's enable register. Not known: whether the real CPU can reach it, which depends on how DBT-RISE's accesses fall across delta cycles. The fix is likely the one the behavioral NVMe needed: a single process that writes the line, with the register write only notifying it. It wants a contract item for the PLIC adapter first: a source that rises in the same delta cycle as a register write.
