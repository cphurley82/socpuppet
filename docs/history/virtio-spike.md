# The virtio spike: what it takes to boot Linux on virtio's whole cast

**In one paragraph.** 🎭 Five virtio devices (entropy, console, disk, network card and a shared directory) now sit behind one `virtio-mmio` transport on the host's IO die, a page apart where QEMU's `virt` machine has its slots, each with 🧵 Python at its far end. Firmware nobody here wrote drives every one of them: Zephyr's own drivers run its entropy test, print its greeting, answer Python's ARP and UDP and list, read and write a shared directory; EDK2's run a FAT disk Python made, `ping` Python and mount the share. Everything ran on both harts, QEMU's through QBox and DBT-RISE's interpreter, and it took two patches to borrowed firmware and one to ours. For Linux, the answer to "what would it take" is: very little of the hardware. A stock RISC-V `defconfig` kernel builds in the transport and the drivers for four of the five, reads its hardware from the devicetree that already matches `virt`'s map where it matters, and can mount its root on the virtio disk with no initramfs and no module, which the planned road (an initramfs first, then NVMe, which `defconfig` builds as a module) cannot. The recommendation is to take that road first, on the host as it is, and keep the planned one as the second. No Linux was booted: that is M20's.

## The question

🎓 **Virtio** is the family of devices a virtual machine offers its guest when it does not pretend to be real hardware: each a small register block and rings of descriptors in the guest's memory. The **virtqueue** is the part they share: the driver puts buffers in a ring, rings a doorbell, and the device fills them and says so with an interrupt. **`virtio-mmio`** is the transport whose register block sits at an address the devicetree gives, which suits a SoC with no PCIe between the CPU and the device.

The plan asked which virtio stand-ins earn a place for M20. The maintainer widened it on 2026-10-16: what would it take to boot Linux with virtio's whole cast, in case a virt-shaped board is a better road to Linux than the planned one (the 16550 and an initramfs, then the real NVMe drive at M24 and the real network card at M17)? Decided with the maintainer, and not re-litigated here: the models live in the tree and are built test-first; five devices, with virtio-fs over 9p because both Zephyr and EDK2 have a client; no Linux and no QEMU boot in M25; QEMU's hart through QBox for the runs, the interpreter as the fallback, and a difference between them is a finding.

## What was tried

Everything is in the tree, test-first, except one comparison script, which was in `spikes/virtio/` and is in the history at `7076cb7`.

- **The transport and the walker.** `regs/virtio_mmio.rdl`, version 2 register for register; `Virtqueue`, a split-ring walker over the driver's memory; `VirtioMmioLogic`, the register block; and `VirtioMmio<Device>`, a SystemC shell that works a delta cycle after the doorbell, with DMA through a bus master port and one interrupt line. Held to one contract suite, which every device passes ([virtio-mmio.md](../models/virtio-mmio.md)).
- **Five devices**, each a plain C++ `VirtioDevice` with unit tests, a shell, a registry name, a catalogue class and a Python far end: [entropy](../models/virtio-rng.md) (seeded), [console](../models/virtio-console.md) (`output` and `write`, as at the UART), [disk](../models/virtio-blk.md) (`load` and `contents`), [network](../models/virtio-net.md) (`send`, `received` and `dropped`) and [file system](../models/virtio-fs.md), whose requests a Python callable answers: `socpuppet.fuse.Directory`, a FUSE server over a real directory.
- 🧵 **Python as the first driver of each**, `socpuppet.virtio_host` ([virtio-host.md](../models/virtio-host.md)), before anyone else's.
- **The host's slots.** `host(virtio=Virtio())` puts the five in slots 0 to 4 at `0x1000_1000` and up, with lines to the IO APLIC from source 18. Off by default, so the host's checked-in devicetree and every other image are untouched. The shield `socpuppet_host_virtio` is their devicetree for Zephyr, and `socpuppet_host_virtio_console` makes the console Zephyr's.
- **Borrowed drivers.** Four of Zephyr's (4.4.2) and four of EDK2's (`edk2-stable202608`), in pytest runs beside the steps: `tests/python/test_virtio_zephyr.py` and `test_virtio_uefi.py`.

## Answers

| Device | Python's driver | Zephyr's driver | EDK2's driver | Linux `defconfig` |
|---|---|---|---|---|
| Entropy (4) | ✅ | ✅ `tests/drivers/entropy/api` passes | ✅ `dh -p Rng` finds it | ✅ `HW_RANDOM_VIRTIO=y` |
| Console (3) | ✅ | ✅ `hello_world` greets through it, 16550 silent | — none in the image | ✅ `VIRTIO_CONSOLE=y` |
| Disk (2) | ✅ | — Zephyr has none | ✅ FAT image read and written as `FS0:` | ✅ `VIRTIO_BLK=y` |
| Network (1) | ✅ | ✅ `echo_server` answers ARP, echoes UDP | ✅ `ifconfig` shows the MAC, `ping` answered | ✅ `VIRTIO_NET=y` |
| File system (26) | ✅ | ✅ the sample lists, reads and creates | ✅ with one patch: mounted by its tag, read and written | ❌ not built (`FUSE_FS`, `VIRTIO_FS` absent) |

Every run passed on both harts. What they took, in wall-clock time on this machine:

| Run | QBox's QEMU hart | DBT-RISE's interpreter |
|---|---|---|
| Each Zephyr image to its verdict | 0.1 to 0.2 s | 0.1 to 0.2 s |
| A UEFI boot to `Shell>`, and its commands | 6 s | 90 s |

⚠️ The UEFI boots are slow for a reason of the boot manager's own: with a network device present it tries PXE over IPv4 before the shell and waits for a DHCP answer nobody sends, about 65 s of simulated time. Without the network device a boot took 49 s on the interpreter. The prompt comes at 234 s of simulated time on QBox's hart and 141 s on the interpreter's, since QEMU's instructions cost more of the CPU's time.

## What was found on the way

The borrowed ones are in [upstream.md](../upstream.md), and the rest in [lessons.md](lessons.md#virtio).

- 📮 **Zephyr's transport reads a register the specification has it only write** (`DRIVER_FEATURES`, to set one bit). QEMU's device answers the read, so ours does too.
- 📮 **Zephyr's table of virtqueue callbacks is misaligned**, 6 bytes past a multiple of 8. QEMU's hart does misaligned stores in hardware and Zephyr's tests never see it; the interpreter traps, as the specification allows. The first patch to Zephyr's tree, which `firmware/build.py` now applies as it does OpenSBI's and EDK2's.
- 📮 **Zephyr's transport allocates its rings from a heap it does not select**; the shield gives it one.
- 📮 **EDK2's `VirtioFsDxe` never says how large its queue is.** Over PCI, where a queue starts at its largest, that is harmless; over virtio-mmio version 2 it makes a queue of none. Our transport divided by that size and the process died of `SIGFPE`. Now the transport keeps an empty queue from becoming ready, and a patch to EDK2 makes the one call its other virtio drivers make.
- **Zephyr's virtio console takes an interrupt a character.** It asks for queues of one entry, so each character after the first waits for the used-buffer interrupt to give its descriptor back: with the transport's interrupt taken out, it says `H`. It also waits for that descriptor inside a spinlock, which works on one hart because the idle thread runs with interrupts on. That is Zephyr's to look at, and not entered upstream.
- **The configuration had been writable.** The disk was the first device with a configuration, and the transport wrote a driver's config writes straight into it, so a driver could change the capacity it read back. The configuration is read-only now unless a device takes a write.
- 💡 **EDK2's boot manager tries the disk before its shell**, looking for `\EFI\BOOT\BOOTRISCV64.EFI`. A disk with that file on it, a bootloader or a kernel's EFI stub, is booted with no shell and no typing.
- **The FUSE server was the riskiest code.** Its design review found a link out of the share reachable through a listing, `RMDIR ..` at the top deleting the share, every one of EDK2's renames refused (it always sends `RENAME_NOREPLACE`), and open flags read in the host's numbers. All are fixed, each with its test. Nothing outside the served directory is reachable now: containment is checked wherever a path is used.
- **Two borrowed Python libraries.** The FAT images are [pyfatfs](https://github.com/nathanhi/pyfatfs)'s, held to `fsck.fat`, which found its two copies of the volume label disagree (📮); and PyFilesystem2 under it still imports `pkg_resources`, so the dev group pins `setuptools<81` (📮). The Ethernet frames are [dpkt](https://github.com/kbandla/dpkt)'s, held to checksums added up by hand.
- **The drivers want different devicetrees.** Zephyr's console, network and entropy drivers bind to a child of the transport's node (`virtio,console`, `virtio,net` with the MAC, `virtio,device4`), its virtiofs client to the transport itself by a label or an alias, and it has no disk driver at all. Linux and EDK2 want the transport's node alone and ask the device what it is.
- **QEMU's samples can be built unchanged.** The virtiofs sample names its device by a label of QEMU's x86 boards; an overlay of ours gives the host's node that label too. The echo server leaves Ethernet's L2 to the board; one Kconfig option of the image's own turns it on.

## The virt-shaped board

`spikes/virtio/compare_virt.py` (at `7076cb7`) read QEMU's own memory map and interrupt numbers out of `hw/riscv/virt.c` and `include/hw/riscv/virt.h`, in QBox's copy of QEMU (10.2.92), and set the host with its slots beside them:

| `virt` region | QEMU's base, size | The host there | Same address? |
|---|---|---|---|
| `DEBUG` | `0x0`, `0x100` | nothing | — |
| `MROM` | `0x1000`, `0xf000` | nothing | — |
| `TEST` | `0x100000`, `0x1000` | `compute.syscon` (`0x100000`, `0x20`) | yes |
| `RTC` | `0x101000`, `0x1000` | `compute.wdt` (`0x101000`, `0x1000`) | yes |
| `CLINT` | `0x2000000`, `0x10000` | `compute.timer` (`0x2000000`, `0x10000`) | yes |
| `ACLINT_SSWI` | `0x2f00000`, `0x4000` | nothing | — |
| `PCIE_PIO` | `0x3000000`, `0x10000` | nothing | — |
| `IOMMU_SYS` | `0x3010000`, `0x1000` | nothing | — |
| `PLATFORM_BUS` | `0x4000000`, `0x2000000` | nothing | — |
| `PLIC` | `0xc000000`, worked out | `compute.aplic` (`0xc000000`, `0x8000`) | yes |
| `APLIC_M` | `0xc000000`, worked out | `compute.aplic` (`0xc000000`, `0x8000`) | yes |
| `APLIC_S` | `0xd000000`, worked out | nothing | — |
| `UART0` | `0x10000000`, `0x100` | `io.uart` (`0x10000000`, `0x8`) | yes |
| `VIRTIO` | `0x10001000`, `0x1000` | `io.rng` (`0x10001000`, `0x200`) | yes |
| `FW_CFG` | `0x10100000`, `0x18` | nothing | — |
| `FLASH` | `0x20000000`, `0x4000000` | nothing | — |
| `IMSIC_M` | `0x24000000`, worked out | `compute.imsic` (`0x24000000`, `0x1000`) | yes |
| `IMSIC_S` | `0x28000000`, worked out | `compute.imsic` (`0x28000000`, `0x1000`) | yes |
| `PCIE_ECAM` | `0x30000000`, `0x10000000` | nothing | — |
| `PCIE_MMIO` | `0x40000000`, `0x40000000` | nothing | — |
| `DRAM` | `0x80000000`, worked out | `compute.ram` (`0x80000000`, `0x4000000`) | yes |

| `virt` line | QEMU's number | The host's |
|---|---|---|
| UART | 10 | 16 at `io.aplic` |
| virtio slot 0 (rng) | 1 | 18 at `io.aplic` |
| virtio slot 1 (console) | 2 | 19 at `io.aplic` |
| virtio slot 2 (blk) | 3 | 20 at `io.aplic` |
| virtio slot 3 (net) | 4 | 21 at `io.aplic` |
| virtio slot 4 (fs) | 5 | 22 at `io.aplic` |

**What matches.** RAM at `0x8000_0000`, the timer at `0x0200_0000`, the IMSIC's two pages at `0x2400_0000` and `0x2800_0000`, the APLIC at `0x0C00_0000`, the UART at `0x1000_0000` and the first virtio slot at `0x1000_1000`, a page apart: the host was drawn from `virt`'s map from M3 on, and the slots took the last of it. Two of `virt`'s addresses hold something else here: `virt`'s test device and real-time clock are where the host has its system controller and watchdog.

**What differs, and what a stock kernel makes of it.** A kernel reads its hardware from the devicetree, so a different address or interrupt number is nothing to it as long as the tree says so, and the host's does. What it cannot do without is a driver for each `compatible`:

| The host has | `compatible` | In `defconfig` |
|---|---|---|
| The hart and its interrupt controller | `riscv`, `riscv,cpu-intc` | ✅ |
| AIA only, no PLIC: an APLIC on each die in MSI mode, and the IMSIC | `riscv,aplic`, `riscv,imsics` | ✅ selected by `RISCV` itself |
| The timer | `riscv,aclint-mtimer` | ✅ through SBI |
| The UART, as the console (`stdout-path`) | `ns16550` | ✅ `SERIAL_8250`, `SERIAL_OF_PLATFORM` |
| Five virtio slots | `virtio,mmio` | ✅ `VIRTIO_MMIO` |
| Reboot and power-off | `syscon-reboot`, `syscon-poweroff` | — Linux asks OpenSBI, which reads these itself |
| The watchdog | `sifive,wdt` | — no driver; harmless |
| With the drive's shield: the root complex | `pci-host-ecam-generic` | ✅ `PCI_HOST_GENERIC` |

What the host does not have of `virt`'s: `fw_cfg` (EDK2 looks for it and goes on without it, as every boot here shows), the second APLIC domain for supervisor mode (M23 left it out), a flash at `0x2000_0000` (the host's boot flash is on the IO die), and PCIe at `0x3000_0000` (the host's root complex comes with the drive's shield, at `0x1010_0000`). ⚠️ Not measured: the host has 64 MiB of RAM, and a `defconfig` kernel and what it needs at boot may want more. That is the first thing a Linux milestone should check.

**So the host with its slots is already the virt-shaped board.** Nothing in this comparison asks for a second board: a kernel would boot on `host(sbi=True, virtio=Virtio())` with the devicetree the host writes, given RAM enough.

## The roads to Linux

Linux 7.3-rc7's `arch/riscv/configs/defconfig`, read on 2026-10-17:

| | The planned road | The virtio road |
|---|---|---|
| Console | 16550 (`SERIAL_8250=y`) | the same, or `hvc0` on the virtio console (`VIRTIO_CONSOLE=y`) |
| Root file system | an initramfs (`BLK_DEV_INITRD=y`), then the NVMe drive at M24 | the virtio disk, `/dev/vda` (`VIRTIO_BLK=y`, `EXT4_FS=y`, `VFAT_FS=y`) |
| What the disk needs | `BLK_DEV_NVME=m`: a module, so an initramfs that loads it, or a kernel configured otherwise; PCIe through the generic ECAM host | nothing beyond `defconfig` |
| Network | the real card, M17 | the virtio card (`VIRTIO_NET=y`), with Python as the neighbour that answers ARP and ping |
| A shared directory | none | 9p (`NET_9P_VIRTIO=y`, `9P_FS=y`) is built in; virtio-fs is not |
| Entropy | none | `HW_RANDOM_VIRTIO=y` |
| How the kernel is loaded | Python puts it in RAM for OpenSBI's `fw_jump` | the same; or UEFI boots its EFI stub (`EFI` defaults on) from the disk's `\EFI\BOOT\BOOTRISCV64.EFI`, as a server's firmware does |
| What Python makes | an initramfs, a cpio archive | a disk image: ext4 for the root, or FAT for the EFI System Partition (`fat_image`) |

🎓 The difference that decides it is the root file system. On the planned road the first boot needs an initramfs, and the first boot from a disk needs an NVMe driver that `defconfig` builds as a module, so it needs an initramfs too, or a kernel built for it. On the virtio road a kernel built with nothing changed mounts its root from the disk the first time, and every device it meets is one whose model is small, tested, and has had three drivers run against it.

## The catalogue

Every virtio device kind Linux's `include/uapi/linux/virtio_ids.h` names that `defconfig` builds a driver for, and what it would cost here, on this transport:

| Kind | Device | `defconfig` | What it would cost here |
|---|---|---|---|
| 1, 2, 3, 4, 26 | network, disk, console, entropy, file system | built in (fs: not built) | done |
| 5 | memory balloon | `VIRTIO_BALLOON=y` | small: an inflate and a deflate queue of page numbers, and a configuration of two counts |
| 7 | remote processor messaging | `RPMSG_VIRTIO=y` | medium: buffers in shared memory between two processors; it would fit the IO manager's link better than a stand-in |
| 8 | SCSI host | `SCSI_VIRTIO=y` | medium: the disk's store behind SCSI's command set (`READ(10)`, `WRITE(10)`, `INQUIRY`, `READ CAPACITY` and a few more); EDK2 has a driver too |
| 9 | 9p transport | `NET_9P_VIRTIO=y` | medium: a 9P2000.L server in Python, as `socpuppet.fuse` is a FUSE one; the shared directory a stock kernel can mount |
| 16 | GPU | `DRM_VIRTIO_GPU=m`, a module | large: 2D resources, transfers and a scanout, and a display to put it on |
| 18 | input | `VIRTIO_INPUT=y` | small: an event queue and a configuration a driver asks about by selecting fields |
| 20 | crypto | `CRYPTO_DEV_VIRTIO=y` | large: a session per key and per algorithm; not worth it for a stand-in |

The rest of the kinds the header names (vsock, IOMMU, memory, pmem, sound, I²C, GPIO, SPI, CAN, the watchdog, Bluetooth, video and more) have drivers in the kernel that `defconfig` leaves out.

## Cost

| | Lines | Notes |
|---|---|---|
| Transport, walker and registers | 780 | `virtio_mmio_logic.h`, `virtqueue.h`, `virtio_device.h`, `regs/virtio_mmio.rdl`, the shell |
| Five devices | 500 logic, 160 shells | the smallest 49 lines (entropy), the largest 150 (disk) |
| 🧵 Python | 1,240 | the host driver (590), the FUSE server (540), the slots (110) |
| Tests | 3,840 | unit, contract, platform, Python, and the two firmware runs |
| Borrowed-firmware patches | 3 | Zephyr's callbacks; EDK2's queue size; ours: an empty queue is never ready |

## Recommendation

1. 🎭 **Keep all five on the host as stand-ins**, behind `host(virtio=Virtio())` as now. Each is small, held to the contract, and has had firmware nobody here wrote run against it. They are what a kernel bring-up needs to tell "the kernel" from "my hardware", which is why the plan asked for them.
2. **Take the virtio road to Linux first.** M20's first boot is a stock `defconfig` kernel on `host(sbi=True, virtio=Virtio())`, loaded by Python for `fw_jump`, with its root on the virtio disk from an ext4 image Python makes, and its console on the 16550. Then the same kernel through UEFI from the disk's EFI System Partition. The planned road (initramfs, NVMe at M24, the real card at M17) stays as the second, and becomes a comparison: the same kernel, the real blocks in place of the stand-ins.
3. **No second board.** The host with its slots already has `virt`'s map where a kernel looks, and a kernel looks at the devicetree, not at addresses. A board of its own would be one more thing to keep equal.
4. **For a shared directory under Linux, 9p before virtio-fs.** A stock kernel has 9p and not virtio-fs. A 9P2000.L server in Python is the same size of job as the FUSE one was, and the FUSE one stays for Zephyr and EDK2.
5. **Check the RAM first.** 64 MiB was enough for everything here; a kernel's first boot is the first thing that may not fit.

## Not exercised

- Linux, on any device. The `defconfig` and the bindings were read, not run.
- QEMU itself, with the same images: QEMU is not installed on this machine, and the comparison read its source.
- Interrupts from EDK2's drivers, which poll; and the console's receive path under Zephyr, which only transmits in `hello_world`.
- `socpuppet run` and twister: neither knows the virtio shields, so these images run from pytest only (a loose end in [roadmap.md](../roadmap.md#loose-ends)).
- A device reset while a held buffer is in flight, from any borrowed driver; a frame dropped for want of room, from any borrowed driver; the disk's `GET_ID` and `FLUSH`, which only Python sent.
- More than one request queue for the file system, the network card's offloads, and every other feature the pages list as left out.

## For docs/upstream.md

📮 Six entries, added with the steps: three for Zephyr (the `DRIVER_FEATURES` read, the misaligned callbacks, the heap), one for EDK2 (the file system's queue size), two for pyfatfs and the PyFilesystem2 under it, and none for QEMU, whose source was read and not run.

## Decisions

Decided on 2026-10-17, by the rules in [vision.md](../vision.md) (real over toy; borrow before building; Linux asks, we build): **the virtio road first.**

- 🎭 The five stand-ins stay on the host, behind `host(virtio=Virtio())`, as recommended.
- M20's first boot is a stock `defconfig` kernel on `host(sbi=True, virtio=Virtio())`, loaded by Python for `fw_jump`, with its root on the virtio disk from an ext4 image Python makes and its console on the 16550. Then the same kernel through UEFI, from the disk's EFI System Partition.
- The planned road, an initramfs and then the NVMe drive, is the second road and the comparison: the same kernel with the real blocks in place of the stand-ins, and the root on the drive at M24.
- No second board.
- For a shared directory under Linux, 9p before virtio-fs.
- The RAM is checked first.

M20's steps are planned when it starts, as every milestone's are; [roadmap.md](../roadmap.md) records the decision under M20, and [decisions.md](decisions.md) its reasons.
