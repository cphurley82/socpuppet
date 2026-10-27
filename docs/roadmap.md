# The roadmap 🧦

Where socpuppet is going, in phases and milestones, and where it is now. [vision.md](vision.md) is the compass this page is read by: it says why anything here is built and the rules that order it. How it got here is in [history/](history/README.md): the decisions, the lessons, and the spike reports. The step-by-step of a finished milestone is in its commits.

## Where we are

Phases 1 to 4 are done: three Zephyr firmwares boot together on a chiplet host and an NVMe SSD, from a ROM and a flash if asked, with the interrupt architecture RISC-V servers use and Zephyr's own test suites running on every board. Phase 5, the road to Linux, is done too: the hart runs the way Linux runs it, OpenSBI and UEFI boot on both harts, and 🐧 a stock Linux kernel boots to a shell that Python, or you (`socpuppet linux`), can type at, with every 🎭 virtio stand-in under Linux's own driver, and its root filesystem on the real SSD, across the die-to-die link, with the SSD's own firmware ([linux.md](linux.md)). From here the real blocks take the rest of the stand-ins' places, one at a time. And the SSD has met a real host: 🐧 this machine's own Linux, through pciem, finds it on its PCIe bus, formats it, mounts it and writes to it, with the SSD's Zephyr firmware being the drive (`socpuppet drive`, [models/pciem-host.md](models/pciem-host.md)). 🔌 And Linux is on this machine's network, with no root, so `ssh -p 2222 root@localhost` reaches it from a second terminal ([linux.md](linux.md#over-ssh)). **M15, the IOMMU, is next**; M17, the first network card of real hardware's kind, waits until Linux asks for one.

A milestone is done when its exit test passes in CI. The table is in the order the milestones are done; the numbers are the order they were planned in, and a milestone keeps its number when it moves, so that nothing written about it changes its meaning.

| # | Milestone | Needs | Exit test | Status |
|---|---|---|---|---|
| M0 | Scaffold and stand-in infrastructure | none | a Python script, standing in for the CPU, reads and writes memory through the stand-in link (`tests/python/test_m0_exit.py`) | ✅ |
| M1 | ISS spike, a decision gate | M0 | a report, and the chosen CPU boots Zephyr's `hello_world` ([history/iss-spike.md](history/iss-spike.md)) | ✅ |
| M2 | PCIe and the behavioral NVMe, no CPUs | M0 | a Python host finds the drive over PCIe, runs Identify, reads and writes blocks (`test_m2_exit.py`) | ✅ |
| M3 | The host boots standalone | M1, M2 | Zephyr's `hello_world` and `synchronization` on `socpuppet_host`; Zephyr's disk test against the behavioral NVMe (`test_m3a_exit.py`, `test_m3b_exit.py`) | ✅ |
| M4 | The SSD boots standalone | M2, M3's CPU kit | M2's host tests and the NVMe contract pass against the SSD's Zephyr firmware (`test_m4_exit.py` and siblings) | ✅ |
| M5 | The IO manager boots standalone | M0, M3's CPU kit | the manager's firmware trains the link and releases the host's reset (`test_m5_exit.py`, `test_m5a_exit.py`) | ✅ |
| M6 | Host firmware and SSD firmware together | M3, M4 | Zephyr's disk test on the host against the Zephyr SSD, neither image changed (`test_m6_exit.py`) | ✅ |
| M7 | The chiplet split | M5a, M6 | M6's test across the real die-to-die link; the trace shows every command, DMA and interrupt crossing it (`test_m7_exit.py`) | ✅ |
| M8 | The full bootchain, three firmwares | M5b, M7 | boot order across three consoles, then end-to-end data integrity, with a debugger on each CPU (`test_m8_exit.py`, `test_gdb.py`) | ✅ |
| M12 | AI processor spike, a decision gate | M8 | a report; each candidate takes one matrix multiply from a descriptor and interrupts ([history/npu-spike.md](history/npu-spike.md)) | ✅ |
| M13 | AIA: interrupts as messages | M8 | the disk test with every interrupt a message to the IMSIC; Zephyr's shell on a console whose interrupt comes through the APLIC; no PLIC in the host's devicetree (`test_m13_exit.py`) | ✅ |
| M14 | Boot ROM, flash, system controller, watchdog | M8 | the three firmwares boot from flash with nothing loaded into RAM; a bad image is refused on the console; an unfed watchdog resets its CPU (`test_m14_exit.py`) | ✅ |
| M21 | Twister and ztest: Zephyr's own tests on the puppet | M14 | Zephyr's suites pass on all three boards under twister in CI, and a ztest suite of ours for each driver ([twister.md](twister.md)) | ✅ |
| M22 | The hart Linux needs | M13 | bare-metal programs run with paging on, in user mode, take a supervisor's interrupt, use the counters, floating point and atomics, and trap where OpenSBI can catch them (`tests/cpp/platform/cpu_test.cpp`) | ✅ |
| M26 | The fast hart, a spike | M22 | a report: the hart timed on every CPU that builds here, and which one ships ([history/speed-spike.md](history/speed-spike.md)) | ✅ |
| M27 | QBox, the second hart | M26 | the bus-master contract, the hart's suite and the Python boots pass on QEMU's CPU, built from source, in CI (`ctest --preset qbox`) | ✅ |
| M23 | OpenSBI boots | M14, M22 | OpenSBI's banner and its test payload on the console, from the ROM and the quick way, on a devicetree in Linux's dialect from `host()` (`test_m23_exit.py`) | ✅ |
| M28 | UEFI boots | M23 | the UEFI shell's prompt, with paging on and the timer ticking in supervisor mode, on both harts; Python types `ver` and `memmap` and resets it (`test_m28_exit.py`) | ✅ |
| M25 | Virtio spike | M23, M28 | five stand-ins behind `virtio-mmio`, driven first by Python and then by Zephyr's and UEFI's own drivers; a report ([history/virtio-spike.md](history/virtio-spike.md)) | ✅ |
| M20 | Linux boots | M23, M25 | a shell prompt on the virtio console, on both harts; Python types `uname -a` and reads the answer; every virtio device under Linux's driver; through UEFI from a server's disk, on demand (`test_m20_exit.py`, [linux.md](linux.md)) | ✅ |
| M24 | A root filesystem on the drive | M8, M20 | Linux's own NVMe driver mounts its root on the Zephyr SSD across the link; a file written from Linux is read back by Python, from the SSD's NAND; through UEFI's own NVMe driver, on demand (`test_m24_exit.py`, [linux.md](linux.md)) | ✅ |
| M30 | The real-host spike, a decision gate | M4, M8 | a report, and this machine's `lsblk` lists the behavioral drive, then the SSD with its Zephyr firmware, through pciem ([history/real-host-spike.md](history/real-host-spike.md)) | ✅ |
| M31 | A real host: Linux on this machine mounts the drive | M30 | on a prepared Linux machine, the SSD with its Zephyr firmware is a new NVMe drive in `lsblk`; `mkfs.ext4`, mount, a file written, unmount; Python reads the file back from the NAND; nightly, in a QEMU guest on GitHub's runner (`test_m31_exit.py`, [models/pciem-host.md](models/pciem-host.md)) | ✅ |
| M29 | A cable to this machine, and ssh | M20, M31 | Linux boots with its network card bridged to this machine's network, with no root needed; `ssh` from this machine answers `uname -a`, on both harts; a file sent by `scp` is read back at the console (`test_m29_exit.py`, [models/ethernet-cable.md](models/ethernet-cable.md)) | ✅ |
| M17 | Ethernet | M13, M20, M29 | Zephyr's `echo_server` answers a datagram Python sends; Linux answers Python's `ping`; the capture opens in Wireshark | deferred 2026-10-27 |
| M15 | IOMMU | M24 | the disk test through a device context the firmware programmed; DMA to an unmapped page is a fault record and an interrupt; then the drive under Linux's IOMMU driver | 🚧 next |
| M19 | AI processor | M12, M13, M14, M15 | an inference whose weights are in flash, its data through the IOMMU, its completion a message, its answer checked from Python; then from Linux user space | |
| M18 | The small essentials: GPIO, SPI, I2C, RTC, TRNG | M13, M20 | Zephyr's sample or test for each, with Python at the far end of the pins; the RTC and TRNG under Linux's drivers | |
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

## Dependencies

```text
M0 ─┬─ M1 (ISS gate) ── M3 host ──────────────┐
    ├─ M2 (PCIe + behavioral NVMe) ── M4 SSD ─┼─ M6 ── M7 ── M8
    └─ M5 IO manager (5a link, 5b firmware) ──┘
```

```text
M8 ─┬─ M12 (NPU gate)
    ├─ M13 AIA ─────────┬─ M21 twister ── M22 the hart ── M26 speed spike ── M27 QBox ── M23 OpenSBI ── M28 UEFI ── M25 virtio spike ── M20 Linux ─┬─ M24 rootfs on the drive ─┬─ M30 real-host spike ── M31 a real host ── M29 a cable to this machine ── M17 Ethernet
    └─ M14 ROM, flash ──┘                                                                                                                          │                           └─ M15 IOMMU ── M19 NPU
                                                                                                                                                   └─ M18 the small essentials
```

The chain through Phase 5 is stricter than the table's "Needs" column, on purpose. M22 could have run beside M21 and came after it so that every later milestone gets a board tested by Zephyr's own suites. M28 comes before M25 so that the spike's block device meets a driver nobody here wrote. M20 does not need UEFI: a kernel boots from `fw_jump` with nothing between, and UEFI is a second way to the same prompt, kept as a tier. After M20 the branches are independent, and the suggested order was M24, M29, M17, M15, M19, M18, then Phase 7 in any order; M24 is done. On 2026-10-22 the maintainer put M30 and M31 first, and M29 after them because both need the same thing: a loop that waits on the wall while the CPU sleeps and looks at a file descriptor meanwhile, which `interact` did for the keyboard and M31's pump now does for `/dev/pciem` too; M30, M31 and M29 are done. On 2026-10-27 the maintainer deferred M17 and took M15 next, since Linux asks for an IOMMU and not for a second network card ([history/decisions.md](history/decisions.md)). M29 came before M17 because `ssh` needs a bridge at the far end of a network card and not a card: the virtio card already answers Linux's `ping` under Linux's own driver, and the real card inherits the bridge. M9 could be pulled forward any time, and could have been since M4.

## How a milestone is done

- Its exit test is automated and runs in GitHub Actions. A spike's exit is a report and a recommendation, and the maintainer decides.
- Every slot has one contract suite; a 🎭 stand-in and the full model both pass it before either is used in a boot. Stand-in configurations from earlier milestones stay in CI.
- Model logic is plain C++, unit-tested without the SystemC kernel; a borrowed model is tested through its contract, behind its adapter.
- Zephyr's own test suites run on every board under twister in CI (from M21), and Linux boots to its prompt in CI every night (from M20). Linux through UEFI from a server's disk, the quick way and from the flash, runs on demand (`SOCPUPPET_ON_DEMAND=1`), which CI's nightly run asks for.

A milestone's steps are planned when it starts, one `/tdd` session each, and live in its commits. When it is done its row above gets a ✅, what it decided goes to [history/decisions.md](history/decisions.md), what it taught to [history/lessons.md](history/lessons.md), and anything it left for later joins the loose ends below.

## What is next

### M15: IOMMU

A device that does DMA writes wherever it is told to. An **IOMMU** is to a device what the MMU is to a program: every address a device uses goes through page tables the operating system owns, and an access that is not mapped is refused and reported. This one follows the RISC-V IOMMU specification: a **device context** says which page table a device's addresses go through, found by the device's ID, and two rings in memory carry commands in and fault records out.

- **Ours, and written to go upstream**: a plain class with a thin model around it, shaped for VPV-Peripherals' `rvi/` directory beside the APLIC and the PLIC, used here through an adapter like any borrowed model. ⚠️ It bends the rule that only socpuppet's own blocks have a register map, on purpose: a block laid out by a specification and written for another project has one in that project's style.
- **The subset is what the drivers touch**: the device directory with one to three levels, the command and fault queues, the interrupt registers, and translation through one stage of Sv39. No second stage, no ATS, no page requests, no remapping of interrupt messages.
- **It sits on the IO die between the root complex and the link**, its interrupt a wire to the APLIC; a second one sits in front of the AI processor in M19.
- ⚠️ **A device has to say who it is.** Nothing on the PCIe link says which device sent an access, and an IOMMU looks the device's ID up first, so the endpoint marks its DMA with its bus, device and function numbers; a master with no PCIe behind it is given an ID as a parameter. The page tables are a die away, so every walk shows in the link's trace, which is why a real IOMMU caches what it walked.
- **Zephyr has no IOMMU subsystem**, so the driver's interface is our own: let a device through untranslated, map a page for it, read a fault. **Linux's `riscv,iommu` driver is the second customer** and the last line of the exit: the drive's DMA goes untranslated under Linux first (M24), and the IOMMU is then put in its path.
- ⚠️ **Linux brings it up and does not translate through it.** In Linux 6.18 the DMA API's IOMMU layer (`CONFIG_IOMMU_DMA`) is built for Arm, x86 and s390 only, so on RISC-V every device gets an identity domain: Linux's driver programs the queues, the device directory and the interrupt, and puts the drive in a device context with no page table (a Bare first stage). Translation under Linux needs VFIO or iommufd, which `defconfig` leaves out. So the translating and faulting lines of the exit are Zephyr's, and Linux's line is the drive behind a context Linux's own driver programmed.
- **Opt-in**: `host(iommu=True)`, beside `drive_blocks`; without it the root complex's DMA goes straight to the link, as today, so every checked-in devicetree and image stays as it is.

Exit: Zephyr's disk test with the drive behind a device context the firmware programmed, first untranslated and then through a page table; a transfer aimed at an unmapped page is a fault record, an interrupt, and the host's memory untouched. Then M24's root filesystem mounted with the drive in a device context Linux's own IOMMU driver programmed, and no fault.

### M17: Ethernet

The first network card of real hardware's kind, in the place of 🎭 the virtio network card M20's Linux answered `ping` on and M29 reached by `ssh`. VPV-Peripherals has an Ethernet MAC of the simplest kind: firmware pushes a frame into a register a word at a time and pulls a received one out the same way, with no descriptor rings and no DMA.

- **The borrowed MAC behind an adapter, held to a contract written first**, as the UART, the timer and the PLIC were.
- 🧵 **Python is the far end of the cable**: M29's `sp.EthernetCable`, which bridges a card to this machine and writes the capture, takes this card's frames too, unchanged: what it needs of a card is `received_since(n)` and `send(frame)`, as Python's own hands on the wire have.
- **The driver is ours**, in socpuppet's Zephyr module, since none exists for this MAC; Zephyr's Stellaris driver is the nearest in shape. 📮 The Linux driver is written here too, since this comes after M20, and both are offered upstream.
- **Its interrupt is a line to the APLIC**, which is why this waits for M13. SCC's library of interfaces has the sockets the MAC uses and is not linked yet.

Exit: Zephyr's `echo_server` on the host answers a datagram Python sends down the cable, having answered Python's ARP request first, and the capture opens in Wireshark. Then, with the host running Linux, Linux answers Python's `ping`.

**Deferred on 2026-10-27.** Linux does not ask for this card: the virtio card already answers `ping` and carries `ssh` under a driver nobody here wrote, and VPV-Peripherals' MAC has no driver in Zephyr or Linux, so both would be ours. Three roads were found, for whenever M17 starts: VPV's `ethmac` with drivers of ours; LiteX's LiteEth, the same simple kind of MAC, which both operating systems drive unchanged, as a model of ours; or a PCIe card, the shape a server has, after a spike. Which one is an open decision below.

### M19: AI processor

M12's gate chose 🎭 a behavioral NPU of ours, a simplified model on the compute die with its arithmetic in Python ([history/npu-spike.md](history/npu-spike.md)). What the host's firmware does is what it would do with any NPU: describe the work, ring a doorbell, wait for an interrupt.

- **The block**: a register map of ours, a queue of descriptors in memory, a handful of operations (matrix multiply, add, clamp at zero), its data moved by DMA through an IOMMU of its own, and its completion a message to the IMSIC. A Zephyr driver, and `firmware/mlp`, a small multi-layer perceptron on an input both sides know.
- 🧵 **The arithmetic is a Python callable, and the library behind it is interchangeable**: numpy is what the default is written with, and torch is a different callable, not a C++ change. Planning M19 says where the callable is set and whether numpy is a dependency of the wheel or an extra.
- 🦜 **Not QBox's Hexagon**, which the spike also ran; it stays a candidate for an optional, from-source component later, behind the same doorbell.

Exit: an inference whose weights were read from flash, whose data went through the IOMMU, whose completion was an interrupt message, and whose answer Python checks against numpy's. Then the same inference from Linux user space, through a UIO driver written here.

### M18: the small essentials

The parts every board has and no milestone has needed, one `/tdd` session each: a contract or unit tests first, a model page, a Zephyr sample that passes, Python at the far end of the wires.

- **GPIO and SPI**: VPV-Peripherals' SiFive blocks behind adapters; Zephyr and Linux both have drivers. With a driver that speaks SPI, the boot flash gets the read command it lacks.
- **I2C**: ours and small, with the OpenCores controller's registers, which Linux drives; 🎭 a Python script plays the device at the other end.
- **RTC**: ours, with the Goldfish clock's registers, which Linux drives; it tells the time Python gives it.
- **TRNG**: one register, seeded from Python so a run can be had again, read through Linux's driver.

Exit: Zephyr's own sample or test for each passes; `date` reads the time Python gave the RTC, and `/dev/hwrng` reads the seeded stream.

### M16: SHRM and the two-socket board

**SHRM** is the shared-memory subsystem: memory on one SoC that another on the same board can use as its own, which is how a server with several sockets, or a tray of accelerators, pools memory. Here it is a pool of memory on the IO die, decoders that put pieces of it into somebody's address map, a port to the other SoC, a mailbox between the two controllers, and a 32-bit core with its kit. It brings a second SoC into the simulation.

- **a) One SoC's SHRM with 🎭 a script for its firmware** (`sp.ShrmFirmware`, as `sp.SsdFirmware` was for the SSD). The decoders have the shape of CXL's for host-managed device memory. Exit: the host maps a piece of its own pool and uses it.
- **b) Two sockets over 🎭 the pass-through link.** `host()` becomes a function that adds a host under a name, as `add_ssd` and `add_manager` are, then `two_socket_board()` places two. Exit: one host writes into the piece it was lent, and the other reads it. ⚠️ A decoder must describe itself as one memory, so that the devicetree walk does not list everything behind it. Six to eight CPUs in one kernel: the quantum and the wall time are measured again here.
- **c) The firmware and a link that has to be brought up**: `firmware/shrm` on `socpuppet_shrm`, lending over the mailbox, across `sp.D2dLink` with a board's latency. Exit: the message crosses the board with every CPU running its own firmware.
- ⚠️ **No protocol is modelled between the sockets**: memory-mapped TLM, as on the die-to-die mainband. Whether it ever should be CXL is an open decision below.

### M9, M10, M11

- **M9, realistic NAND**: geometry, program and erase times, erase-before-write, file-backed storage, bad blocks and bit errors behind hooks, held to the NAND contract; the FTL gains garbage collection.
- **M10, validation scenarios**: boot-sequencing variants and failures, the link down and retrained during I/O, cross-die data integrity, power loss, IOPS and latency figures. A scenario a Linux milestone needs is pulled forward and becomes that milestone's test.
- **M11, power and telemetry** on the IO die, to be defined. 🦜 The Verilator RTL block this used to list went on 2026-10-12: no block of ours has RTL to put there.

## Open decisions

Each has a date it must be settled by and what happens until then.

| Decision | Settle by | Until then |
|---|---|---|
| A `native_sim` firmware tier | optional, any time | not built |
| Which network card M17 is: VPV's `ethmac` with drivers of ours, LiteX's LiteEth as a model of ours under both operating systems' own drivers, or a PCIe card after a spike | when M17 starts | 🎭 the virtio card, under Linux's and Zephyr's own drivers |
| Does the boot ROM check an image's signature, which is what makes a boot secure? | after M14, when somebody asks | a CRC and nothing more |
| A protocol between sockets, CXL or one like it, where M16 has memory-mapped TLM | after M16 | none |
| A die of its own for the AI processor; the host's DRAM on the IO die | after M16 | one compute die a socket, with the DRAM and the NPU on it |
| A self-hosted runner (the A51 box) for the tests a GitHub runner cannot run, and perhaps QBox's nightly build, faster. 💡 M31's real host needed none: its tests run in a QEMU guest on GitHub's runner, on KVM, as pciem's own CI does ([development.md](development.md#pciem-a-real-host)) | when a job needs one | every job on GitHub's runners |
| Which CPU ships in the wheel, and whether a faster one is offered beside it | when a translating backend passes the hart's suite ([history/speed-spike.md](history/speed-spike.md)) | DBT-RISE's interpreter; QBox beside it, built from source, as a second opinion |
| Should a board's hardware be written as data that Python loads? Asked by the maintainer on 2026-10-10: addresses, devices, buses, links and interrupt lines in a TOML, JSON or YAML file that `Platform.load(file)` turns into the same `add`, `map`, `connect` and `link` calls, so that `build()`, the devicetree generator, the address map and `to_json()` are untouched; variants as a file laid over another, as Zephyr lays a shield over a board. A flow where Python generates the description as JSON and the simulation or the devicetree tools read it back could be good, and might even replace SystemRDL. What gets awkward: a script in a CPU's place changes the hardware, so the SSD and the IO manager each split into several files, and the host converts cleanly while the other two would likely read worse than their one Python file. Doing everything in Python alone, with no conversion, must stay possible | when somebody wants it | boards are Python functions; if tried, the host alone first, with its checked-in `.dts` unchanged as the proof that nothing moved |

## Loose ends

Small things that are nobody's milestone. Each links to where its detail lives.

- Reserve the `socpuppet` name on PyPI before the first wheel is published (free as of 2026-10-04; needs the maintainer's account).
- Send the fixes we carry upstream, smallest and clearest first; [upstream.md](upstream.md) is the list.
- Run the C++ NVMe contract against the SSD with its Zephyr firmware. `SsdRig` in `tests/cpp/contracts/nvme_test.cpp` has a C++ stand-in where the CPU goes; the firmware's share of the contract is held by `tests/python/test_ssd_firmware.py` until then.
- Mend, or send, what QBox and QEMU get wrong: an atomic to memory without direct access never completes, and a misaligned atomic raises a load's cause ([models/qbox-cpu.md](models/qbox-cpu.md), [upstream.md](upstream.md)).
- Make a translating backend pass the hart's suite, LLVM first: M22's fixes are in the interpreter, and each backend has its own copy of every instruction ([history/speed-spike.md](history/speed-spike.md), [upstream.md](upstream.md)).
- Let whichever CPU is stopped in its debugger answer every debugger; today a debugger reads memory only while its own CPU is the one stopped ([history/gdb-spike.md](history/gdb-spike.md); the test to write first is in `tests/python/test_gdb.py`).
- Give the CPU user mode behind a PMP, so Zephyr's `CONFIG_USERSPACE` suites can run: a core name and a PMP layer in `dbt_rise_cpu.cpp` ([twister.md](twister.md), [history/twister-spike.md](history/twister-spike.md)).
- Have `build()` refuse an address map that loops, as `Platform.address_map()` does; the test to write first is in `tests/python/test_platform.py`.
- Teach `socpuppet run`, and so twister, the two virtio shields; until then the virtio images run from pytest only.
- Ship the boot ROM images in the wheel, or say how they are built; and let `firmware/build.py` take its image list from `twister --build-only`.
- A second APLIC domain with delegation, the faithful step after the one domain Linux's driver takes ([models/aplic.md](models/aplic.md)).
- Paging beyond Sv39, 2 MiB pages, ASIDs, `wfi` in user mode and the vector state: what no test has run on the hart yet ([models/dbt-rise-cpu.md](models/dbt-rise-cpu.md)).
- The sideband packet's layout lives twice, in C++ and in `socpuppet.ucie`, kept in step only by a decode test; and the reserved gaps in register maps are named by hand in each block's tests.
- Linux's console on the 16550, the next hardware block to take a virtio stand-in's place under Linux, after the drive took the disk's (M24) and before M17 takes the network card's ([linux.md](linux.md)).
- A boot flash big enough for a kernel: it is 16 MiB with the manager's image at its end, and a `defconfig` kernel is 26 MiB, so from the flash Linux comes through UEFI from the disk; a bigger flash is the maintainer's decision.
- A Debian root beside Alpine's mini root, for a reader who wants `apt`.
- The virtio console's size feature (`F_SIZE`), so that `socpuppet linux` tells Linux the terminal's size and its changes; until then `vi` and `top` assume 80 by 24 ([linux.md](linux.md)).
- An instruction trace on the DBT-RISE CPU, whose `enable_disass` goes to its own logger; QBox's is QEMU's, through the debugger ([models/qbox-cpu.md](models/qbox-cpu.md)).
- QBox's hart under the pump, on an Intel Mac: `socpuppet linux --cpu qbox_cpu` boots at the wall's pace, three to four minutes, where `examples/linux_hello.py` on the same hart prompts in 5 s, and `ssh` to it, from the command or from `examples/linux_cable.py`, is closed by dropbear at the key exchange every time, with either key exchange, while the interpreter's answers in half a minute. The pump takes a CPU whose next activity is further off than a quantum for a sleeping one, and QBox's hart, which runs ahead of the clock, reports its next activity hundreds of seconds off while it works, so the pump runs the simulation only as far as the wall moved between looks (`tests/python/test_m29_exit.py` boots unpumped for the first reason). [linux.md](linux.md) and the command's own first line say seconds. Found by [the Linux lab](labs/linux-tour.md) on 2026-10-26.
- A guard in `opensbi.lay_out` for a kernel too big for the gap before the devicetree's copy, which only `tests/python/test_linux_images.py` checks today, for our own kernel.
- Delete I/O Submission and Completion Queue on the drive: Linux sends both at every shutdown and reset, both firmwares and the behavioral drive answer Invalid Opcode, and Linux, which marks admin commands quiet, carries on and says nothing, on the simulated host and on this machine's ([models/ssd-firmware.md](models/ssd-firmware.md), [history/real-host-spike.md](history/real-host-spike.md)).
- The drive's `VS` reads zero, so Linux takes NVMe 1.0's road; a version, with what a newer driver then sends (Identify's other CNS values, Get Log Page, asynchronous events), is the step after.
- Several I/O queues under this machine's Linux: pciem's virtual bus gives the drive one legacy interrupt, so Linux makes one I/O queue; pciem's attach mode, which puts the device on an existing bus, is untried ([models/pciem-host.md](models/pciem-host.md)).
- A recipe for pciem in a Linux VM on a Mac, for a real host where this machine is not Linux ([setup.md](setup.md#6-pciem-optional)).
- Get Log Page, for the SMART log at least: Linux 7.0 on x86 asks for it at every probe, all three drives answer Invalid Opcode, and Linux says `Failed to read smart log` and carries on ([history/real-host-spike.md](history/real-host-spike.md)).
- Power lost without a shutdown: the SSD's table is saved only when the host shuts the drive down, so a drive whose power just goes keeps the table it last saved. A table rebuilt from the pages, or saved as it goes, belongs with M10's power-loss scenarios.
- The NVMe frontend's ztest (`zephyr_module/tests/drivers/nvme_frontend`) does not yet have its shield's host shut the drive down; the SSD's contract tests hold both firmwares to the shutdown.
- The 9P messages `socpuppet.ninep` answers `EOPNOTSUPP`: `Tremove`, `Trename`, `Tlink`, locks and extended attributes ([models/virtio-9p.md](models/virtio-9p.md)).

Known bugs with no milestone:

- **A debugger that detaches, or quits at a breakpoint, leaves its CPU stopped** and the simulation with it; the fix is a patch to DBT-RISE-Core, and until then [boot-your-firmware.md](boot-your-firmware.md) says to leave with `continue` ([upstream.md](upstream.md)).
- **A debugger that attaches before the simulation runs is shown registers from before the CPU's reset**; the tests' client waits on a memory read first, and the docs start the run before GDB attaches ([upstream.md](upstream.md)).

## Keeping this page

This page replaced `docs/plan.md` on 2026-10-17, which had grown to half a megabyte of steps, findings and status; commit `5be2b90` is the last that holds it. What was worth keeping is in [history/](history/README.md). This page stays short: a phase a line, a milestone a row and, for the ones not yet done, a section of a screen; the rest goes to the history pages and the commits.
