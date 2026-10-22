# The real-host spike: this machine's own Linux mounts the puppet's SSD

**In one paragraph.** 🐧 This machine's own Linux (Ubuntu 26.04, kernel 7.0, on x86) found the puppet's SSD on its PCIe bus, bound its own `nvme` driver to it, and used it as a disk: `lsblk` listed it, `mkfs.ext4` formatted it, a file was written, unmounted, mounted again and read back, the controller was reset and the file survived, and the driver let go of it with a clean shutdown. It did so for all three of the drive's casts: 🎭 the behavioral stand-in, the SSD with the C++ firmware stand-in in its CPU's place, and the SSD with Zephyr's firmware on its RISC-V core, through the frontend, the DMA engine, the flash controller and the NAND. The bridge is [pciem](https://github.com/cakehonolulu/pciem), a kernel framework that lets a program be a PCIe device, and 1,400 lines of spike in `spikes/pciem/`. Nothing in the firmware or the models changed. Every step took well under a second of wall time, inside Linux's patience by a factor of thirty at the least; Zephyr's SSD ran ahead of the wall. Two things stood in the way and are worked around in the bridge: the behavioral drive says its controller is ready in no time at all, which Linux reads as "do not wait", and pciem does not clear the memory the host reads registers from. Two things limit what the spike could see: pciem's virtual bus gives the device one interrupt line and not MSI-X, so Linux used one I/O queue, and pciem's header is GPL-2.0-only. The recommendation is to build M31 as planned, with the corrections below.

## The question

🎓 To its host, a **PCIe device** is three things: registers at an address (its BARs, the base address registers), DMA into the host's memory, and interrupts. A **root complex** is the host's side of PCIe, where the CPU's bus becomes PCIe. **pciem** is a Linux kernel module that plays the root complex, a device's configuration space and its BARs on this machine's own bus, and hands a program in userspace the rest: the BAR as shared memory, a ring of the host's writes to it with an eventfd to wake on, an ioctl for DMA and one for interrupts. There is no virtual machine between the program and the host's driver.

So pciem stands where the puppet's endpoint, link, root complex and host CPU stand, and the NVMe function behind the endpoint is unchanged: its three ports, `bar0`, `dma` and the `irq` lines, are the whole interface. The roadmap asked seven questions; M31's gate was `lsblk` listing the behavioral drive, then the SSD with Zephyr's firmware.

## What was tried

Everything is in `spikes/pciem/` (README there), C++, behind the `spike` preset.

- **`fetch.sh`** clones pciem at `f80bbb71` (2026-09-30) into `build/pciem` and builds its module and its NVMe example against the running kernel, with `-Werror` as pciem's CI does.
- **`PciemDevice`** (`pciem_device.h`, `.cpp`): the `/dev/pciem` calls, in the one file that includes pciem's header. A device of BAR0 (8 KiB of registers) and BAR2 (the MSI-X table and its pending bits, as pciem's example has them), the puppet's IDs and NVMe's class code.
- **`PciemBridge`** (`pciem_bridge.h`): a SystemC module with the mirror of the function's ports. A host write from the ring becomes a bus write on `bar0`, made by a process of the bridge's own; a DMA from the function becomes `PCIEM_IOCTL_DMA`; a line going high becomes `PCIEM_IOCTL_INJECT_IRQ`.
- **The pump** (`host_spike.cpp`): `interact`'s loop from `socpuppet.interactive`, in C++. It drains the ring into the bridge, runs the simulation a 100 µs slice at a time while anything is due within a slice, and otherwise waits on the eventfd for as long as the next activity is away (at most a second), then runs the simulation for the wall time that passed. After each round it copies the registers the host reads into BAR0's memory.
- **The three drives** (`rigs.h`): the behavioral drive; the SSD with the C++ firmware stand-in, as the NVMe contract's `SsdRig` builds it; and the SSD with its CPU, read from the board Python's `add_ssd_function` describes (`describe_ssd.py` writes it out, a line a component and a line a connection), with Zephyr's ELF put into its SRAM through the CPU's socket, as `Platform.load_elf` does. All three 64 MiB, two interrupt vectors, as the boards have them.
- **`exercise.sh`**, run as root: each drive in turn, found by where it is (under pciem's bus) and never by name, a 4 KiB write and read with direct I/O, `mkfs.ext4`, mount, a 1 MiB file and a small one written, unmount, mount read-only and compare, `e2fsck -fn`, a controller reset, mount and compare again, and the driver unbound.

The machine needed a reboot, once: pciem's BARs live in memory set aside on the kernel's command line (`memmap=64M$0x10000000`, in a file of its own in `/etc/default/grub.d/`), and the module is loaded with `insmod` after. Both need root; the program that is the drive does not, as `/dev/pciem` is open to everyone.

## Answers

### 1. Does it run here?

✅ Yes. pciem builds against Ubuntu's kernel 7.0 with `-Werror`, with no change. Secure Boot is off on this machine, so the unsigned module loads, tainting the kernel. pciem's own NVMe example appears as `nvme2n1`, "PCIem Virtual NVMe SSD", 1 GiB, with one finding (below: the BAR's memory is not cleared). ⚠️ This machine has two NVMe drives of its own, `nvme0` and `nvme1`, so the puppet's drive is `nvme2n1` and not the `nvme0n1` M31's exit names.

### 2. A host that reads a copy

The device keeps **CAP, VS and CSTS** fresh, copied from the function's registers by a debug read after every round of the pump. **CC, AQA, ASQ and ACQ** are left to pciem's shadow write, which lands each host write in BAR0's memory before posting it, so the host reads back what it wrote, where a copy from the function, made before the write reached it, could hand the host an older value than the one it just wrote. The doorbells are the host's too.

`CSTS.RDY` was in BAR0's memory 0.03 to 0.2 ms after `CC.EN` was written:

| Drive | `CC.EN` to `CSTS.RDY`, at first | after a reset |
|---|---|---|
| 🎭 Behavioral | 0.043 ms | 0.032 ms |
| SSD, C++ firmware stand-in | 0.060 ms | 0.038 ms |
| SSD, Zephyr's firmware | 0.203 ms | 0.176 ms |

That is fast enough for Linux, as long as the drive asks it to wait at all. ⚠️ **The behavioral drive says `CAP.TO` is 0**, and Linux 7.0 waits `(CAP.TO + 1) / 2` whole seconds for `CSTS.RDY`, which is no time: the probe failed with `Device not ready; aborting initialisation, CSTS=0x0`, though the bridge had set ready 0.03 ms after. Inside the puppet the host's driver runs on the same clock as the drive, and no wall time passes. The SSD's frontend says 2, one second, and is fine. The spike's `--least-timeout 1` shows the host a `CAP.TO` of at least 1.

### 3. The pump

A loop outside the SystemC kernel drains the ring, and a process inside it makes the writes on the bus, a delta cycle later: a register write may wait, and nothing outside a process may. The loop wakes on the eventfd, so a doorbell is answered at once; while the drive is busy it runs in slices and looks at the ring between them.

| Drive, the whole run | On the bus | Waiting on the wall | Simulating | Simulated | Deepest drain |
|---|---|---|---|---|---|
| 🎭 Behavioral | 0.64 s | 0.61 s | 0.03 s | 0.61 s | 13 writes |
| SSD, C++ firmware stand-in | 0.66 s | 0.61 s | 0.05 s | 0.60 s | 11 writes |
| SSD, Zephyr's firmware | 2.19 s | 0.38 s | 1.76 s | 3.92 s | 9 writes |

⚠️ pciem's ring has 256 slots and drops a write when it is full, with a warning in the kernel's log; the most ever waiting was 16. Zephyr's SSD ran ahead of the wall, because its CPU's 100 µs slices took less than 100 µs. The cost of one wake-up on its own was not measured: a 4 KiB write with `dd` took 17 ms on the behavioral drive, nearly all of it `dd` starting.

### 4. Wall time against Linux's patience

Every step, the second run, in wall time with the program's own start included. Linux gives an I/O command 30 s and an admin command 60 s.

| Step | 🎭 Behavioral | Stand-in SSD | Zephyr's SSD |
|---|---|---|---|
| The drive appears in `lsblk` | 0.139 s | 0.141 s | 0.134 s |
| 4 KiB written, direct | 0.017 s | 0.017 s | 0.142 s |
| 4 KiB read back, direct, the same bytes | 0.017 s | 0.017 s | 0.012 s |
| `mkfs.ext4`, 64 MiB | 0.025 s | 0.035 s | 0.941 s |
| mount | 0.019 s | 0.018 s | 0.119 s |
| 1 MiB and `spam` written, `sync` | 0.025 s | 0.028 s | 0.283 s |
| unmount, mount read-only, the file compared | 0.056 s | 0.055 s | 0.157 s |
| `e2fsck -fn`, clean | 0.017 s | 0.017 s | 0.015 s |
| controller reset, live again | 0.047 s | 0.047 s | 0.051 s |
| mount, the file compared again | 0.034 s | 0.038 s | 0.157 s |
| driver unbound, shut down | 0.080 s | 0.084 s | 0.089 s |

The first run, without the reset, took 0.92 s for Zephyr's `mkfs.ext4` and 1.00 s for its 1 MiB. Zephyr's firmware boots in 50 ms of simulated time before the drive goes on the bus (13 ms of wall time), so it is ready before Linux asks. A larger drive, whose table takes longer to read at boot (0.27 s of simulated time for 2 GiB), was not tried.

### 5. What an x86 host sends

The bridge logged every controller register write and every command on the admin queues.

- **Registers**: `CC` = 0, `AQA`, `ASQ` and `ACQ` as two 4-byte halves each, `CC` = `0x460000` and then `0x460001`. ✅ **No 8-byte write**, so the frontend's refusal of one never came up. At unbind, `CC` = `0x464001`: a normal shutdown, and Linux reported none timed out.
- **Admin commands at probe**: Identify the controller; Get Log Page for the SMART log (`0x02`, log 2); Set Features, the number of queues, asking for 24 (one a CPU); Create I/O Completion Queue and Submission Queue 1, of 1024 entries each; Identify the controller and the namespace again. Then the partition table's reads, on queue 1.
- **What the drives answered that Linux minded**: Get Log Page is Invalid Opcode on all three, and Linux says `Failed to read smart log (error 1)` and carries on.
- **What the drives answered that Linux did not mind**: Delete I/O Submission Queue and Delete I/O Completion Queue, at every reset and unbind, are Invalid Opcode on all three. Linux says nothing. `VS` reads 0; Linux 7.0 said nothing of it either.
- **A queue a CPU**: Linux asked for 24, all three drives answered 8, and Linux used **1**. Not because of the drives: pciem's virtual bus has no MSI domain, so the device gets one legacy interrupt (INTx), every "vector" injected goes to that one line, and Linux makes as many I/O queues as it has interrupts to spare. Multiple queues cannot be tried through pciem as it is.
- **The device's IDs matter.** The spike first borrowed QEMU's NVMe IDs (1b36:0010). Linux knows them and works around QEMU: one I/O queue whatever it has (`SHARED_TAGS`), command identifiers of its own (`SKIP_CID_GEN`), and `Ignoring bogus Namespace Identifiers` (`BOGUS_NID`). With the puppet's own, 5350:C0DE from `boards/drive.py`, the last went away.
- `nvme id-ctrl`: not run, as `nvme-cli` is not installed here. What it would read is the Identify the bridge logged.

What mount and unmount need: nothing the drives do not already do.

### 6. The licence

pciem's kernel side is GPLv2 and its examples are dual MIT/GPLv2, but `include/pciem_api.h`, the header a program must include to say anything to `/dev/pciem`, is `GPL-2.0-only` without the `Linux-syscall-note` that Linux's own user-API headers carry, which says a program using them is not a derived work. socpuppet is MIT. So the bridge stays optional, from source and out of the wheel, as decided, and 📮 the authors are asked for the syscall note or the examples' dual licence on the header ([upstream.md](../upstream.md#pciem)). In the spike only `pciem_device.cpp` includes it; it needs C++23 for its `<stdatomic.h>`, and SystemC, built for C++20, refuses to link with C++23, so nothing else could.

### 7. Where the test can run

On this machine, by hand: it needs the reservation at boot, the module loaded, and root for `mkfs` and mount. 💡 Not necessarily a self-hosted runner, though: pciem's own CI loads the module in a QEMU guest on GitHub's `ubuntu-latest`, with KVM where it is offered, booting Ubuntu's kernel with `mem=2G` so that the RAM above 2 GiB is the region, and a busybox initramfs. An M31 test there would need the drive's program and its libraries in the guest. Not tried.

## What was found on the way

The borrowed ones are in [upstream.md](../upstream.md#pciem), and the rest in [lessons.md](lessons.md#a-real-host-through-pciem).

- 📮 **pciem does not clear the memory a BAR lives in.** The host reads every register it is not given, and Linux 7.0 reads the controller memory buffer's (CMBLOC and CMBSZ) before it enables anything. With pciem's own NVMe example, which writes only CAP and VS, whatever was in that RAM became a CMB size, and UBSAN reported a shift out of bounds in `nvme_map_cmb`. The bridge zeroes BAR0 before the device starts.
- 📮 **pciem's virtual root has no MSI domain**, so MSI-X is advertised and unusable: one interrupt, one I/O queue.
- 📮 **pciem's NVMe example closes the wrong descriptor at teardown** (`close(dev->event_fd >= 0)`) and allocates its 1 GiB disk twice.
- **The behavioral drive's `CAP.TO` of 0** works against a simulated host and not against a real one (answer 2). A model to change in M31.
- **The roadmap was wrong about Zephyr's table**: Zephyr's firmware reads it once at boot (`ftl_start`) and does not clear it on `CC.EN`. The file written before the reset was read back after it.
- **A placeholder ID is not neutral.** Linux keeps a table of devices with quirks, and QEMU's NVMe is in it (answer 5).
- **Debug reads made the bridge simple.** Every model on the NVMe path answers one, so the pump could copy CAP, VS and CSTS from outside the simulation without a process or a bus cycle, as M2 had arranged for another reason.
- **The board as Python describes it was easy to borrow.** `Platform.to_json()` has every component, parameter and connection, and the C++ side built the Zephyr SSD from it with nothing copied by hand; `ReadElfImage` and `DebugWrite` loaded the firmware in a dozen lines. The roadmap thought no C++ path could boot a Zephyr ELF; one could, and the spike's is it.
- ⚠️ **`timeout` cannot run a shell function.** The first reset ran `/usr/bin/reset`, the terminal's, which sat waiting on the terminal. Recorded because it is the kind of thing that costs an evening.

## Cost

One day, 2026-10-22, and one reboot. 1,400 lines in `spikes/pciem/`, two tests that need no `/dev/pciem` (the ring, drained from ordinary memory; the bridge's writes made on the behavioral drive), and four root steps the maintainer ran: the GRUB file and `update-grub`, the reboot, `insmod`, and `exercise.sh`.

## Recommendation

**Build M31 as planned**, with these changes, and keep the pump for M29:

- **`sp.PciemHost` is the spike's bridge, rebuilt test-first**: the ring drained outside the kernel and the writes made by a process inside it; CAP, VS and CSTS copied into BAR0 after every round; BAR0 cleared before the device starts; a vector sent on each rising line, and again after a completion queue's head doorbell while the line is still high, a delta cycle on, since MSI-X is edges and the lines are levels. The puppet's own IDs.
- **The pump in Python**, in `socpuppet.interactive`, waiting on the far end's file descriptor as it waits on the keyboard: the board is then Python's own `ssd()` with `PciemHost` where the scripted host goes, and the C++ copy of the board the spike needed goes away.
- **The behavioral drive says a `CAP.TO` of at least 1**, held by the NVMe contract, and the bridge shows the host what the drive says.
- **No firmware work is needed to mount**: Delete I/O Queue, Get Log Page and `VS` stay loose ends. Get Log Page joins them, since Linux complains at every probe.
- **The exit finds the drive by its place on pciem's bus**, as `exercise.sh` does, and not as `/dev/nvme0n1`.
- **Try pciem's own way to CI first**, a QEMU guest on a hosted runner, before a self-hosted runner, and ask pciem's authors for the header's licence.
- **One queue is what pciem gives**, and M31's test should not depend on more.

## Not exercised

- A drive larger than 64 MiB, and so the boot time of a big table against the host's patience.
- Several I/O queues, and so the firmwares' answer of 8 under load (pciem's single interrupt).
- `nvme-cli`; a Linux on Arm; pciem's attach mode, which puts the device on an existing bus.
- The cost of one wake-up, separate from the program that caused it.
- Power lost without a shutdown, with Zephyr's table: the drive was always unbound before it went.

## For upstream.md

The pciem section: the header's licence, the BAR's memory, the virtual root's interrupts, and the example's teardown.

## Decisions

🚧 For the maintainer.
