# The roadmap 🧦

Where socpuppet is going, in phases and milestones, and where it is now. [vision.md](vision.md) is the compass this page is read by: it says why anything here is built and the rules that order it. How it got here is in [history/](history/README.md): the decisions, the lessons and the spike reports. The step-by-step of a finished milestone is in its commits.

## Where we are

Phases 1 to 5 are done, and Phase 6 all but M19, the AI processor, and M17, Ethernet, which waits until Linux asks for a card. **Phase 8, the first release, is next**, starting with M32: socpuppet is useful enough to put in strangers' hands, and the release gate in [vision.md](vision.md#the-release-gate) says what that takes. Phase 9, the memory, follows it, and M19 comes after both.

A milestone is done when its exit test passes in CI. The table is in the order the milestones are done; the numbers are the order they were planned in, and a milestone keeps its number when it moves, so that nothing written about it changes its meaning.

| # | Milestone | Needs | Exit test | Status |
|---|---|---|---|---|
| M0 | Scaffold and stand-in infrastructure | none | a Python script, standing in for the CPU, reads and writes memory through the stand-in link (`tests/python/test_scripted_bus_master_across_the_dies.py`) | ✅ |
| M1 | ISS spike, a decision gate | M0 | a report, and the chosen CPU boots Zephyr's `hello_world` ([history/iss-spike.md](history/iss-spike.md)) | ✅ |
| M2 | PCIe and the behavioral NVMe, no CPUs | M0 | a Python host finds the drive over PCIe, runs Identify, reads and writes blocks (`test_nvme_over_pcie.py`) | ✅ |
| M3 | The host boots standalone | M1, M2 | Zephyr's `hello_world` and `synchronization` on `socpuppet_host`; Zephyr's disk test against the behavioral NVMe (`test_zephyr_on_the_host_board.py`, `test_zephyr_disk_on_the_host.py`) | ✅ |
| M4 | The SSD boots standalone | M2, M3's CPU kit | M2's host tests and the NVMe contract pass against the SSD's Zephyr firmware (`test_ssd_with_its_own_firmware.py` and siblings) | ✅ |
| M5 | The IO manager boots standalone | M0, M3's CPU kit | the manager's firmware trains the link and releases the host's reset (`test_link_training.py`, `test_io_manager_lets_the_compute_die_go.py`) | ✅ |
| M6 | Host firmware and SSD firmware together | M3, M4 | Zephyr's disk test on the host against the Zephyr SSD, neither image changed (`test_host_and_ssd_firmware_together.py`) | ✅ |
| M7 | The chiplet split | M5a, M6 | M6's test across the real die-to-die link; the trace shows every command, DMA and interrupt crossing it (`test_host_across_the_real_link.py`) | ✅ |
| M8 | The full bootchain, three firmwares | M5b, M7 | boot order across three consoles, then end-to-end data integrity, with a debugger on each CPU (`test_full_bootchain.py`, `test_gdb.py`) | ✅ |
| M12 | AI processor spike, a decision gate | M8 | a report; each candidate takes one matrix multiply from a descriptor and interrupts ([history/npu-spike.md](history/npu-spike.md)) | ✅ |
| M13 | AIA: interrupts as messages | M8 | the disk test with every interrupt a message to the IMSIC; Zephyr's shell on a console whose interrupt comes through the APLIC; no PLIC in the host's devicetree (`test_zephyr_shell.py`) | ✅ |
| M14 | Boot ROM, flash, system controller, watchdog | M8 | the three firmwares boot from flash with nothing loaded into RAM; a bad image is refused on the console; an unfed watchdog resets its CPU (`test_rom_boot.py`) | ✅ |
| M21 | Twister and ztest: Zephyr's own tests on the puppet | M14 | Zephyr's suites pass on all three boards under twister in CI, and a ztest suite of ours for each driver ([twister.md](twister.md)) | ✅ |
| M22 | The hart Linux needs | M13 | bare-metal programs run with paging on, in user mode, take a supervisor's interrupt, use the counters, floating point and atomics, and trap where OpenSBI can catch them (`tests/cpp/platform/cpu_test.cpp`) | ✅ |
| M26 | The fast hart, a spike | M22 | a report: the hart timed on every CPU that builds here, and which one ships ([history/speed-spike.md](history/speed-spike.md)) | ✅ |
| M27 | QBox, the second hart | M26 | the bus-master contract, the hart's suite and the Python boots pass on QEMU's CPU, built from source, in CI (`ctest --preset qbox`) | ✅ |
| M23 | OpenSBI boots | M14, M22 | OpenSBI's banner and its test payload on the console, from the ROM and the quick way, on a devicetree in Linux's dialect from `host()` (`test_opensbi_boots.py`) | ✅ |
| M28 | UEFI boots | M23 | the UEFI shell's prompt, with paging on and the timer ticking in supervisor mode, on both harts; Python types `ver` and `memmap` and resets it (`test_uefi_boots.py`) | ✅ |
| M25 | Virtio spike | M23, M28 | five stand-ins behind `virtio-mmio`, driven first by Python and then by Zephyr's and UEFI's own drivers; a report ([history/virtio-spike.md](history/virtio-spike.md)) | ✅ |
| M20 | Linux boots | M23, M25 | a shell prompt on the virtio console, on both harts; Python types `uname -a` and reads the answer; every virtio device under Linux's driver; through UEFI from a server's disk, every night (`test_linux_boots.py`, [linux.md](linux.md)) | ✅ |
| M24 | A root filesystem on the drive | M8, M20 | Linux's own NVMe driver mounts its root on the Zephyr SSD across the link; a file written from Linux is read back by Python, from the SSD's NAND; through UEFI's own NVMe driver, every night (`test_linux_root_on_the_drive.py`, [linux.md](linux.md)) | ✅ |
| M30 | The real-host spike, a decision gate | M4, M8 | a report, and this machine's `lsblk` lists the behavioral drive, then the SSD with its Zephyr firmware, through pciem ([history/real-host-spike.md](history/real-host-spike.md)) | ✅ |
| M31 | A real host: Linux on this machine mounts the drive | M30 | on a prepared Linux machine, the SSD with its Zephyr firmware is a new NVMe drive in `lsblk`; `mkfs.ext4`, mount, a file written, unmount; Python reads the file back from the NAND; nightly, in a QEMU guest on GitHub's runner (`test_this_machines_linux_mounts_the_ssd.py`, [models/pciem-host.md](models/pciem-host.md)) | ✅ |
| M29 | A cable to this machine, and ssh | M20, M31 | Linux boots with its network card bridged to this machine's network, with no root needed; `ssh` from this machine answers `uname -a`, on both harts; a file sent by `scp` is read back at the console (`test_ssh_over_the_cable.py`, [models/ethernet-cable.md](models/ethernet-cable.md)) | ✅ |
| M17 | Ethernet | M13, M20, M29 | Zephyr's `echo_server` answers a datagram Python sends; Linux answers Python's `ping`; the capture opens in Wireshark | deferred 2026-10-27 |
| M15 | IOMMU | M24 | the disk test through a device context the firmware programmed, untranslated and through page tables; DMA to an unmapped page is a fault record and an interrupt; then the root on the drive in a context Linux's own IOMMU driver programmed (`test_iommu.py`, [models/iommu.md](models/iommu.md)) | ✅ |
| M18 | The small essentials: GPIO, SPI, I2C, RTC | M13, M20 | Zephyr's sample or test for each, with Python at the far end of the pins; the boot flash and the RTC under Linux's drivers (`test_zephyr_peripheral_samples.py`, `test_linux_boot_flash.py`, `test_linux_rtc.py`, [models/spi-flash.md](models/spi-flash.md)) | ✅ |
| M32 | Images fetched on first use | M14, M20 | the wheel alone, with no checkout, fetches the images and boots Zephyr's `hello_world` and Linux to its prompt, in CI (`test_fetched_images.py`) | |
| M33 | QBox in one command | M27 | one command on a bare checkout ends with Linux at a prompt on QBox's hart, on Linux, macOS and WSL, in CI | |
| M35 | The docs, read by a stranger | M32, M33 | no machine's or person's name outside the licence and `pyproject.toml`; every link resolves, under lint; a stranger reaches a boot from the front door | |
| M36 | The release: PyPI and the tap | M32, M35 | the release gate in [vision.md](vision.md#the-release-gate): the README's first show from `pip install socpuppet` on Linux, macOS and WSL and from the tap on a Mac, each release built, tested and published from its tag | |
| M37 | The container | M33, M36 | the release's image opens as a devcontainer in VS Code and in a Codespace, and `docker run` of it boots Linux on both harts with nothing fetched or built, in CI | |
| M34 | Labs in twenty-minute sketches | M36, M37 | every lab states a measured length under twenty minutes and its Python steps run under ctest; the 🌱 first-rung lab needs nothing but one of the release's channels | |
| M38 | The memory spike, a decision gate | M14, M5 | a report (`history/memory-spike.md`): which controller, who brings it up, where the DRAM lives, what Linux and Zephyr ask, which timed model is the tier later | |
| M39 | The DRAM controller | M38 | the three firmwares boot from flash with the host's RAM behind a controller firmware brought up, a read before that a bus error on the trace, Linux's prompt unchanged (`test_ddr_controller.py`) | |
| M19 | AI processor | M12, M13, M14, M15 | an inference whose weights are in flash, its data through the IOMMU, its completion a message, its answer checked from Python; then from Linux user space | |
| M16 | SHRM and the two-socket board | M13 | two hosts in one simulation: one writes into memory the other's SHRM lent it, and the other reads it on its console | |
| M9 | Realistic NAND and garbage collection | M4 | M4's and M6's tests pass under sustained writes | |
| M10 | Validation scenarios | M8, M9 | the scenario suite | |
| M11 | Stretch: power and telemetry | M8 | to be defined | |

## The phases

1. **Foundation.** Infrastructure and 🎭 stand-ins, no CPUs. (M0 to M2)
2. **Each subsystem boots its own firmware**, with everything around it stood in. (M3 to M5)
3. **The full bootchain.** The three images together, one stand-in swapped for the real thing per milestone. (M6 to M8)
4. **The cast of a real SoC.** The interrupt architecture, the boot ROM, and Zephyr's own tests, with Zephyr still the firmware that boots. (M12 to M14, M21)
5. **The road to Linux.** The hart and the board run the way Linux will run them, then OpenSBI, then UEFI, then the kernel. (M22 to M28, M20, M24)
6. **Linux grows, and meets this machine.** A real host for the SSD, a cable to this machine, Ethernet, the IOMMU, the AI processor and the small parts, each under Linux's own driver. (M30, M31, M29, M17, M15, M19, M18)
7. **The rest of the cast, and fidelity.** What nothing on the road to Linux needs. (M16, M9, M10, M11)
8. **The first release.** Images fetched on first use, QBox in one command, the docs read by a stranger, the wheel on PyPI and a Homebrew tap with Windows through WSL, a container that opens in VS Code with both harts inside, and then the labs in twenty-minute sketches. (M32 to M37)
9. **Memory.** Where the DRAM lives, and a DRAM controller firmware brings up. (M38, M39)

Phases 8 and 9 come before the rest of 6 and 7 ([history/decisions.md](history/decisions.md), 2026-10-31). Where the order is stricter than the table's "Needs" column, it is on purpose: M22 came after M21 so that every later milestone gets a board tested by Zephyr's own suites; M28 before M25 so that the spike's block device met a driver nobody here wrote; M29 before M17 because `ssh` needs a bridge at the far end of a card, not a card; M36 after M35 because the README it ships must be true; M37 after M36 because the image is built from the release's wheel and images; M34 last, after both releases, because the channels a release ships through shape how every lab begins. The rest of the ordering, and why, is in [history/decisions.md](history/decisions.md).

## How a milestone is done

- Its exit test is automated and runs in GitHub Actions. A spike's exit is a report and a recommendation, and the maintainer decides.
- Every slot has one contract suite, which a 🎭 stand-in and the full model both pass before either is used in a boot ([vision.md](vision.md#what-socpuppet-does-differently)); stand-in configurations from earlier milestones stay in CI.
- Model logic is plain C++, unit-tested without the SystemC kernel; a borrowed model is tested through its contract, behind its adapter.
- Zephyr's own test suites run on every board under twister in CI, and every boot of Linux runs every night.

A milestone's steps are planned when it starts, one `/tdd` session each, and live in its commits. When it is done its row gets a ✅, what it decided goes to [history/decisions.md](history/decisions.md), what it taught to [history/lessons.md](history/lessons.md), and what it left for later joins the loose ends.

## What is next

What each milestone delivers, and why. How is planned when it starts.

### M32: Images fetched on first use

An installed wheel boots real firmware with nothing built: the images come from a release the first time they are needed. Aim 3 of [vision.md](vision.md#the-aims), a firmware team installs the wheel and boots, and *a newcomer builds it for free*.

- Not inside the wheel, which stays small and MIT-only; the kernel stays stock.

### M33: QBox in one command

The second hart from a bare checkout in one command, on Linux, macOS and Windows under WSL. A second opinion is worth having only if a newcomer can get one.

- 🦜 Never a QBox wheel: GPL stays out of what PyPI ships.

### M35: The docs, read by a stranger

Every page read as a stranger reads it: the project's own machines, people and dates out, what a contributor needs kept. The gate's front door, and the bottom rung's three rules ([vision.md](vision.md#who-it-is-for)).

- 🌱 The gate's first rung is this milestone's: one page and one example that need nothing but Python, where the reader changes a line and the chip does something different. The labs build on it.

### M36: The release: PyPI and the tap

`pip install socpuppet` on Linux, macOS and WSL, a Homebrew tap on a Mac, and a release that builds, tests and publishes itself from a tag. Aim 2, deliver it with `pip install`; the release gate is its exit.

- ⚠️ The maintainer's own hands: the PyPI account and name, the trusted publisher, the tap's repository.
- After it, the post per act and the upstream track open ([vision.md](vision.md#the-release-gate)).

### M37: The container

The release as an image, with the wheel installed, the images fetched and QBox's hart built, that opens as a devcontainer in VS Code or a Codespace and runs with `docker run`. For a Windows machine with nothing set up, a classroom that wants every seat the same, and the second hart without the build: the one channel that can carry QBox, since GPL stays out of the wheel but not out of an image whose sources are offered.

- The contributors' devcontainer stays what it is, a build environment.

### M34: Labs in twenty-minute sketches

The Linux tour split, and a lab for each thing socpuppet does: each a sketch of twenty minutes, in the ladder of the four readers, from 🌱 install and change a line to 🐧 a real host. Aim 1: a chip is learned one block at a time. Written after the releases, because how a reader installed is how every lab begins.

### M38: The memory spike

A report: which real controller the model stands for and how a real boot brings DRAM up; where the DRAM lives, the compute die as today or the IO die as a chiplet server's; what Linux and Zephyr ask of a controller; and which open timed model becomes the tier when a question asks. It settles the open decision on the DRAM's die, and looks before anything is written, by *borrow before building*.

- Timing stays out of M39: *what a block does matters; how long it takes is a tier*.

### M39: The DRAM controller

The host's RAM behind a controller that firmware brings up before anything is loaded into it, 🎓 which is why a chip has SRAM and a boot ROM at all; a stand-in that is up from reset and the model, both kept. Aim 1, and *every block arrives the same way*.

- It leaves the timed tier, ECC and file-backed contents as loose ends.

### M19: AI processor

🎭 A behavioral NPU of ours, a simplified model on the compute die whose arithmetic is in Python, chosen by M12's gate ([history/npu-spike.md](history/npu-spike.md)). What the host's firmware does is what it would do with any NPU: describe the work, ring a doorbell, wait for an interrupt; then the same from Linux user space.

- 🧵 The arithmetic is a Python callable and the library behind it is interchangeable: numpy by default, torch a different callable and not a C++ change.
- Its data goes through an IOMMU of its own and its completion is a message, which is why it waits for M13 and M15.
- 🦜 Not QBox's Hexagon, which the spike also ran; a candidate for an optional, from-source component later, behind the same doorbell.

### M17: Ethernet

The first network card of real hardware's kind, in the place of 🎭 the virtio card that Linux answers `ping` on and `ssh` reaches. Deferred because Linux does not ask for it ([history/decisions.md](history/decisions.md), 2026-10-27); which card it is, is an open decision below.

### M16: SHRM and the two-socket board

**SHRM** is the shared-memory subsystem: memory on one SoC that another on the same board can use as its own, which is how a server with several sockets pools memory. Here it is a pool on the IO die, decoders that put pieces of it into somebody's address map, a port to the other SoC, a mailbox between the two controllers, and a 32-bit core with its kit. In three steps:

- **a) One SoC's SHRM with 🎭 a script for its firmware**: the host maps a piece of its own pool and uses it.
- **b) Two sockets over 🎭 the pass-through link**: one host writes into the piece it was lent, and the other reads it. Six to eight CPUs in one kernel, so the quantum and the wall time are measured again.
- **c) The firmware, and a link that has to be brought up**, with a board's latency.
- ⚠️ No protocol is modelled between the sockets: memory-mapped TLM, as on the die-to-die mainband. Whether it should be CXL is an open decision below.

### M9, M10, M11

- **M9, realistic NAND**: geometry, program and erase times, erase-before-write, file-backed storage, bad blocks and bit errors behind hooks, held to the NAND contract; the FTL gains garbage collection. It could be pulled forward any time.
- **M10, validation scenarios**: boot-sequencing variants and failures, the link down and retrained during I/O, cross-die data integrity, power loss, IOPS and latency figures.
- **M11, power and telemetry** on the IO die, to be defined.

## Open decisions

Each has a date it must be settled by and what happens until then.

| Decision | Settle by | Until then |
|---|---|---|
| A `native_sim` firmware tier | optional, any time | not built |
| Which network card M17 is: VPV's `ethmac` with drivers of ours, LiteX's LiteEth as a model of ours under both operating systems' own drivers, or a PCIe card after a spike | when M17 starts | 🎭 the virtio card, under Linux's and Zephyr's own drivers |
| Does the boot ROM check an image's signature, which is what makes a boot secure? | when somebody asks | a CRC and nothing more |
| A protocol between sockets, CXL or one like it, where M16 has memory-mapped TLM | after M16 | none |
| A die of its own for the AI processor; the host's DRAM on the IO die | in M38 | one compute die a socket, with the DRAM and the NPU on it |
| A self-hosted runner for the tests a GitHub runner cannot run; 💡 M31's real host needed none, its tests run in a QEMU guest on GitHub's runner ([development.md](development.md#pciem-a-real-host)) | when a job needs one | every job on GitHub's runners |
| Which CPU ships in the wheel, and whether a faster one is offered beside it | when a translating backend passes the hart's suite ([history/speed-spike.md](history/speed-spike.md)) | DBT-RISE's interpreter; QBox beside it, built from source, and in the container |
| A board's hardware as data that Python loads: a TOML, JSON or YAML file that `Platform.load(file)` turns into the same `add`, `map`, `connect` and `link` calls, with variants laid over one another as Zephyr lays a shield over a board; everything in Python alone must stay possible | when somebody wants it | boards are Python functions; if tried, the host alone first, with its checked-in `.dts` unchanged as the proof that nothing moved |
| conda-forge, and native Windows wheels | when somebody asks | PyPI and the tap; Windows through WSL |

## Loose ends

Small things that are nobody's milestone, each with a link to where its detail lives.

- Send the fixes we carry upstream, smallest and clearest first ([upstream.md](upstream.md)).
- Run the C++ NVMe contract against the SSD with its Zephyr firmware: `SsdRig` in `tests/cpp/contracts/nvme_test.cpp` has a C++ stand-in where the CPU goes, and `tests/python/test_ssd_firmware.py` holds the firmware's share until then.
- Mend, or send, what QBox and QEMU get wrong with atomics ([models/qbox-cpu.md](models/qbox-cpu.md), [upstream.md](upstream.md)).
- Make a translating backend pass the hart's suite, LLVM first ([history/speed-spike.md](history/speed-spike.md), [upstream.md](upstream.md)).
- Let whichever CPU is stopped in its debugger answer every debugger ([history/gdb-spike.md](history/gdb-spike.md); the test to write first is in `tests/python/test_gdb.py`).
- Give the CPU user mode behind a PMP, so Zephyr's `CONFIG_USERSPACE` suites can run ([twister.md](twister.md), [history/twister-spike.md](history/twister-spike.md)).
- Have `build()` refuse an address map that loops, as `Platform.address_map()` does; the test to write first is in `tests/python/test_platform.py`.
- Teach `socpuppet run`, and so twister, the two virtio shields; until then the virtio images run from pytest only.
- The IOMMU caches nothing and reads a device context as four doublewords; DTF is refused; a master with no PCIe has no device ID until M19 ([models/iommu.md](models/iommu.md)).
- Translation under Linux, whose DMA API has no IOMMU layer on RISC-V in 6.18 and leaves a device untranslated ([models/iommu.md](models/iommu.md)).
- A second APLIC domain with delegation ([models/aplic.md](models/aplic.md)).
- The IO die's APLIC has no wire source left for a next device: the split moved, or a second APLIC ([address-map.md](address-map.md)).
- 🐧 I2C under Linux, whose driver is not in the stock kernel; a config fragment is the maintainer's decision ([models/i2c-controller.md](models/i2c-controller.md)).
- 🐧 A GPIO pin driven, and its interrupt taken, under Linux ([models/gpio.md](models/gpio.md)).
- The SPI controller's frame format and its memory-mapped mode ([models/spi-flash.md](models/spi-flash.md)).
- A shield's devices are a keyword of `host()` each and a branch in `socpuppet run`; a table from shield to keywords, at the next one.
- Paging beyond Sv39, 2 MiB pages, ASIDs, `wfi` in user mode and the vector state ([models/dbt-rise-cpu.md](models/dbt-rise-cpu.md)).
- The sideband packet's layout lives twice, in C++ and in `socpuppet.ucie`, kept in step only by a decode test; and the reserved gaps in register maps are named by hand in each block's tests.
- Linux's console on the 16550, the next hardware block to take a virtio stand-in's place ([linux.md](linux.md)).
- A boot flash big enough for a kernel ([linux.md](linux.md)).
- A Debian root beside Alpine's mini root, for a reader who wants `apt`.
- The virtio console's size feature, so that `vi` and `top` learn the terminal's size ([linux.md](linux.md)).
- An instruction trace on the DBT-RISE CPU; QBox's is QEMU's ([models/qbox-cpu.md](models/qbox-cpu.md)).
- QBox's hart under the pump runs at the wall's pace, and `ssh` to it is closed at the key exchange ([models/qbox-cpu.md](models/qbox-cpu.md#what-it-leaves-out)).
- A guard in `opensbi.lay_out` for a kernel too big for the gap before the devicetree's copy, which only `tests/python/test_linux_images.py` checks today.
- The admin commands Linux sends that every drive here answers Invalid Opcode to, Delete I/O Submission and Completion Queue and Get Log Page; and a version in `VS`, which reads zero so Linux takes NVMe 1.0's road ([models/ssd-firmware.md](models/ssd-firmware.md), [history/real-host-spike.md](history/real-host-spike.md)).
- Several I/O queues under this machine's Linux, which pciem's one legacy interrupt keeps at one ([models/pciem-host.md](models/pciem-host.md)).
- A recipe for pciem in a Linux VM on a Mac ([setup.md](setup.md#6-pciem-optional)).
- Power lost without a shutdown, with M10's power-loss scenarios ([models/ssd-firmware.md](models/ssd-firmware.md)).
- The NVMe frontend's ztest does not yet have its shield's host shut the drive down; the SSD's contract tests hold both firmwares to it.
- The 9P messages `socpuppet.ninep` answers `EOPNOTSUPP` ([models/virtio-9p.md](models/virtio-9p.md)).

Known bugs with no milestone, both in the borrowed debugger server ([upstream.md](upstream.md)): a debugger that detaches, or quits at a breakpoint, leaves its CPU stopped, so [boot-your-firmware.md](boot-your-firmware.md) says to leave with `continue`; and one that attaches before the simulation runs is shown registers from before the CPU's reset, so the docs start the run first.

## Keeping this page

This page replaced `docs/plan.md` on 2026-10-17; commit `5be2b90` is the last that holds it, and what was worth keeping is in [history/](history/README.md). A phase is a line, a milestone a row, an undone milestone a few lines of what and why; the how is in the history pages and the commits.
