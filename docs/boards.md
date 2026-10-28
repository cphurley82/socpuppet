# The boards, and the bigger shows 🧦

socpuppet has three Zephyr boards, the host (`socpuppet_host`), the SSD's controller (`socpuppet_ssd`) and the IO die's manager (`socpuppet_iomgr`), and shows that put two or three of them on stage together. This page is how to run each. The steps are the host's, from [boot-your-firmware.md](boot-your-firmware.md), and each section says what differs. 🎭 A stand-in is a simplified model that holds a block's place so the rest can rehearse; every show here starts with one and says how to swap in the real thing.

## With a drive

The host can have an SSD on a PCIe link: 🎭 the [behavioral NVMe](models/behavioral-nvme.md) behind a [PCIe endpoint](models/pcie-endpoint.md). Zephyr finds it by scanning the bus and uses it through its own NVMe driver and its disk API (`disk_access_read` and friends, on the disk `nvme0n0`).

| What | Where | Zephyr driver |
|---|---|---|
| PCIe root complex, configuration window | `0x1010_0000`, one bus | `socpuppet,pcie`, from socpuppet's module |
| PCIe root complex, memory window | `0x1120_0000`, 1 MB | |
| NVMe drive | found by the scan | `nvme-controller` |

🎓 Zephyr calls hardware that is plugged into a board a *shield*. The drive, and the host's side of its link, are the shield `socpuppet_host_drive`. Name it when you build:

```sh
west build -b socpuppet_host --shield socpuppet_host_drive my_app -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

The shield adds the devices to the devicetree and switches on PCIe and the NVMe driver. Your application adds `CONFIG_DISK_ACCESS=y`. Then describe the host with a drive, of as many 512-byte blocks as you like:

```python
board = host(drive_blocks=4096)     # 2 MB
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf")
```

`tests/python/test_zephyr_disk_on_the_host.py` is a complete example. It runs Zephyr's own test of its disk interface, unchanged.

💡 The same image runs against the real SSD, with firmware of its own behind it: see [The host with the SSD](#the-host-with-the-ssd).

⚠️ Firmware built with the shield needs the drive. On a host described without one it stops before it prints anything: the first place it looks for the drive is an address where nothing answers.

💡 A PCIe device interrupts with a message, and the board's interrupt controller is one that is sent messages, so the drive's interrupts go to it as they are: identities 32 and 33, written to `0x2400_0000`. [The IMSIC's page](models/imsic.md) has the rest.

### Behind an IOMMU

The host can have an [IOMMU](models/iommu.md) in front of its drive, which confines the drive to the memory firmware gave it: `host(drive_blocks=4096, iommu=True)`, and the shield `socpuppet_host_iommu` after `socpuppet_host_drive`.

| What | Where | Zephyr driver |
|---|---|---|
| IOMMU | `0x100E_0000`, a page; its line at the IO die's APLIC, source 24 | `riscv,iommu`, from socpuppet's module |

```sh
west build -b socpuppet_host --shield "socpuppet_host_drive;socpuppet_host_iommu" my_app -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

The module's driver sets the IOMMU up and, before Zephyr scans the bus, lets the drive through untranslated. With `CONFIG_SOCPUPPET_RISCV_IOMMU_IDENTITY_PAGE_TABLE=y` it gives the drive page tables instead, which map the RAM and each IMSIC's page to themselves, and your application can take pages away and give them back, and read what the drive did wrong, through `<socpuppet/drivers/riscv_iommu.h>`. `tests/python/test_iommu.py` runs Zephyr's disk test both ways, unchanged, and the driver's own test, which takes a page away from the drive.

## With the virtio slots

🎭 The host can have six virtio devices on its IO die, a page apart from `0x1000_1000` where QEMU's `virt` machine has its slots: an entropy source, a console, a disk, a network card and a shared directory, served twice, to Zephyr and EDK2 by the file system device and to Linux by the 9P transport, with 🧵 Python at the far end of each. Every Linux has drivers for them, and so do Zephyr and EDK2. [virtio-spike.md](history/virtio-spike.md) says why they are there, and each has [a page](models/virtio-mmio.md).

| Slot | What | Where | Zephyr driver binds to | Python's end |
|---|---|---|---|---|
| 0 | [Entropy source](models/virtio-rng.md) | `0x1000_1000` | `virtio,device4`, `chosen` as `zephyr,entropy` | its `seed` |
| 1 | [Console](models/virtio-console.md) | `0x1000_2000` | `virtio,console` | `output`, `write()` |
| 2 | [Disk](models/virtio-blk.md) | `0x1000_3000` | none: Zephyr has no virtio disk driver | `load()`, `contents` |
| 3 | [Network card](models/virtio-net.md) | `0x1000_4000` | `virtio,net`, with `local-mac-address` | `send()`, `received`, `received_since()`, `dropped`; 🔌 [`sp.EthernetCable`](models/ethernet-cable.md) plugs it into this machine's network |
| 4 | [Shared directory](models/virtio-fs.md) | `0x1000_5000` | the transport itself, by the alias `virtiofs0` | a directory of this machine |
| 5 | [Shared directory, for Linux](models/virtio-9p.md) | `0x1000_6000` | none: Zephyr has no 9P client | the same directory |

The slots are the shield `socpuppet_host_virtio`. A second shield, `socpuppet_host_virtio_console`, makes the virtio console Zephyr's console in place of the 16550, and turns off the boot banner, which Zephyr's virtio console driver will not be built with. Stack them:

```sh
west build -b socpuppet_host \
    --shield "socpuppet_host_virtio;socpuppet_host_virtio_console" my_app -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

Then describe the host with its slots, and say what the devices are to be:

```python
from socpuppet.boards.virtio import Virtio

board = host(virtio=Virtio(blocks=2048, share="/tmp/share", tag="spam"))
board.platform.build()
board.virtio.blk.load(disk_image)          # before the run
board.platform.load_elf("build/zephyr/zephyr.elf")
board.platform.run(sp.ms(100))
print(board.virtio.console.output)
```

`tests/python/test_virtio_zephyr.py` runs four of Zephyr's own tests and samples against them, unchanged, `tests/python/test_virtio_uefi.py` boots UEFI with them, and `tests/python/test_linux_boots.py` boots 🐧 Linux with every one under its own driver ([linux.md](linux.md)). 💡 The slots are off unless asked for (`virtio=None`), so the host's devicetree and every image built without the shield are as they were. ⚠️ `socpuppet run`, and so twister, does not know the virtio shields yet: run such an image from Python.

## The SSD's controller

The second board is `socpuppet_ssd`: the controller inside the SSD, which is where an SSD's firmware runs. It is a 32-bit RISC-V machine, with the SSD's hardware around it.

| What | Where | Zephyr driver |
|---|---|---|
| CPU | RV32IMAC, machine mode, starts at `0x2000_0000` | |
| SRAM, which the firmware runs from | `0x2000_0000`, 256 KiB | |
| Buffer, which data passes through | `0x4000_0000`, 4 MiB | (a second `memory` node, `ssd_buffer`) |
| Machine timer | `0x0200_0000`, 10 MHz | `riscv,machine-timer` |
| Interrupt controller (PLIC) | `0x0C00_0000`, 31 sources | `sifive,plic-1.0.0` |
| UART, the console | `0x1000_0000` | `ns16550` |
| [NVMe frontend](models/nvme-frontend.md) | `0x1001_0000`, PLIC source 1 | `socpuppet,nvme-frontend` |
| [DMA engine](models/dma-engine.md) | `0x1002_0000`, PLIC source 2 | `socpuppet,dma-engine` |
| [Flash controller](models/flash-controller.md) | `0x1003_0000`, PLIC source 3 | `socpuppet,flash-controller`, a Zephyr flash device |

The last three drivers are socpuppet's own, in its Zephyr module. [Bring up your SSD firmware](#bring-up-your-ssd-firmware) says how to use them. First, the board by itself.

Build for it by naming the board:

```sh
west build -b socpuppet_ssd samples/hello_world -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

The SSD is never alone: it has a host on its PCIe link. `ssd()` describes both, with 🎭 a script for the host, and `idle_host` is a host that does nothing, for when only the firmware matters.

```python
import socpuppet as sp
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd

board = ssd(host=idle_host)
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf", via=board.ssd.cpu.socket)

board.platform.run(sp.ms(100))
print(board.ssd.cpu_kit.uart.output)
```

```text
*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_ssd/socpuppet_rv32
```

Or `python -m socpuppet.boards.ssd build/zephyr/zephyr.elf`.

- ⚠️ **Say whose firmware it is.** The platform has two places an image could go, so `load_elf` wants `via=board.ssd.cpu.socket`. The same goes for the devicetree: `socpuppet devicetree python/socpuppet/boards/ssd.py --via ssd.cpu.socket` is the SSD's own CPU's view, and the host is not in it.
- **Everything below applies**: waiting for output, looking inside, and GDB, with `ssd(host=idle_host, gdb_port=1234)` and the same `riscv64-zephyr-elf-gdb`, which debugs 32-bit code too.
- `tests/python/test_zephyr_on_the_ssd_controller.py` is a complete example.

### Bring up your SSD firmware

`hello_world` boots on the board and is no drive: the host on the link enables the controller and waits for an answer that never comes. Firmware that answers is [`firmware/ssd`](../firmware/ssd/README.md) in socpuppet's repository, a Zephyr application of a few hundred lines. Build it as it is, or start your own from it:

```sh
west build -b socpuppet_ssd /path/to/socpuppet/firmware/ssd -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

The three drivers are built because the board has the devices. The flash controller's is a driver of Zephyr's flash class, so the application asks for that with `CONFIG_FLASH=y`.

| Device | What firmware calls | Header |
|---|---|---|
| NVMe frontend | `nvme_frontend_wait`, `_acknowledge`, `_say_ready`, `_read_command`, `_post`, `_create_queue`, `_get_limits` | `<socpuppet/drivers/nvme_frontend.h>` |
| DMA engine | `dma_engine_copy_from_host`, `dma_engine_copy_to_host` | `<socpuppet/drivers/dma_engine.h>` |
| Flash controller | `flash_read`, `flash_write`, `flash_erase`, `flash_get_size`, `flash_get_write_block_size` | `<zephyr/drivers/flash.h>`, Zephyr's own |

The least a firmware can do and still be found by a host is to say it is ready:

```c
#include <socpuppet/drivers/nvme_frontend.h>
#include <zephyr/device.h>

static const struct device *const frontend = DEVICE_DT_GET_ONE(socpuppet_nvme_frontend);

int main(void)
{
	for (;;) {
		uint32_t happened = nvme_frontend_wait(frontend);

		if (happened & NVME_FRONTEND_STATUS_DISABLED) {
			nvme_frontend_acknowledge(frontend, NVME_FRONTEND_STATUS_DISABLED);
		}
		if (happened & NVME_FRONTEND_STATUS_ENABLED) {
			nvme_frontend_acknowledge(frontend, NVME_FRONTEND_STATUS_ENABLED);
			nvme_frontend_say_ready(frontend);
		}
		if (happened & NVME_FRONTEND_STATUS_COMMAND_WAITING) {
			/* Read it, do it, and post how it went. Here: refuse it. */
			nvme_frontend_post(frontend, 0x01 /* Invalid Command Opcode */, 0);
		}
	}
}
```

A host finds that drive, and gets no further than its first command:

```text
NvmeError: The controller failed the Set Features command: Invalid Command Opcode (status code type 0, status code 0x01).
```

Everything after that is deciding what each command means, which is the rest of `firmware/ssd`. This is a host for it. 🎭 It is a script, and the same one whichever firmware the SSD has:

```python
import socpuppet as sp
from socpuppet.boards.scripted_host import bring_up_the_drive
from socpuppet.boards.ssd import ssd

read_back = []

def host():
    nvme = yield from bring_up_the_drive()      # waits for "ready"
    yield from nvme.write_blocks(first=7, data=b"spam".ljust(512, b"\0"))
    read_back.append((yield from nvme.read_blocks(first=7, count=1)))

board = ssd(host=host, blocks=4096)
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf", via=board.ssd.cpu.socket)

board.platform.run_until(lambda: bool(read_back), timeout=sp.ms(1000))
print(board.ssd.cpu_kit.uart.output)
```

`examples/ssd_firmware_hello.py` is that, with more to say for itself.

- ⚠️ **End the run yourself.** A script comes to an end and a CPU does not, so `platform.run()` with nothing to stop it would go on for ever. `run_until` with a timeout ends it when the host has what it wanted, or when it is plain that it never will.
- ⚠️ **See to a reset before an enable**, and acknowledge it last. Acknowledging a reset is a promise that the firmware has let go of every queue and command from before it. [The frontend's page](models/nvme-frontend.md) has the handshake, and why.
- ⚠️ **A write the hardware refuses is a bus fault.** Zephyr stops and prints the CPU's registers on the console, under `mcause: 7, Store/AMO access fault`. The line to read is `mtval`, which is the address that was refused: `10010034` is the frontend's `QUEUE_CREATE`. `nvme_frontend_create_queue` with a queue the frontend cannot keep is the usual one, so check what the host asked for first, as `firmware/ssd/src/admin.c` does.
- **Data goes through the buffer.** The DMA engine and the flash controller are given addresses on the SSD's bus and do the copying themselves, so what they are pointed at has to be memory. The 4 MiB at `0x4000_0000` is there for it: `DT_NODELABEL(ssd_buffer)` in the devicetree. Zephyr does not manage it, so the firmware carves it up by hand.
- **A NAND is written a page at a time** (`flash_get_write_block_size`), and read that way too when it is data: a read of whole pages goes straight from the chip to the memory you name. `flash_read` will fetch any bytes you like, as Zephyr asks of every flash driver, by way of a page the driver keeps. ⚠️ No more than 2 GiB of a NAND can be reached through Zephyr's flash API from a 32-bit CPU. [upstream.md](upstream.md) says why.
- **The NAND is a little bigger than the drive.** Its first blocks are the reserve where the FTL keeps its table, one block of 256 KiB up to a NAND of 1008 blocks, and the drive is the rest, the size it was described as. `ftl_start` takes the table from there when it is this drive's, `ftl_save` puts it back, and a shutdown from the host is when (`STATUS_SHUTDOWN`). [ssd-firmware.md](models/ssd-firmware.md) has the layout, which `socpuppet.ftl` reads and writes from Python.
- 💡 **Switch on the log** (`CONFIG_LOG=y` and `CONFIG_LOG_MODE_MINIMAL=y`). A driver that cannot start says why there, in a line that starts `E:`, and without it all firmware can find out is that the device is not ready.
- **Hold it to the tests.** `tests/python/test_ssd_firmware.py` is what a host may expect of an SSD's firmware, a behaviour a test, and it runs whatever `ssd_socpuppet_ssd.elf` it finds in `SOCPUPPET_FIRMWARE_DIR`. Put your image there under that name and see how far it gets.
- 🎭 **Or do without the CPU.** [`sp.SsdFirmware`](models/ssd-firmware.md) is the same firmware as a Python script, for when the SSD's firmware is not what you are working on.

## The host with the SSD

The host and the SSD's controller in one simulation: the host's CPU runs the host's firmware, and its SSD's CPU runs the SSD's. Nothing is built differently for it. The host cannot tell the SSD from 🎭 the stand-in drive, and the SSD cannot tell a CPU from 🎭 a scripted host, so each image is the one you already have:

```sh
west build -d build/host -b socpuppet_host --shield socpuppet_host_drive my_app -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
west build -d build/ssd -b socpuppet_ssd /path/to/socpuppet/firmware/ssd -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

Then tell the host which drive to have. `add_ssd` is the function that describes the SSD, and handing it to `host` puts one on the host's PCIe link:

```python
import socpuppet as sp
from socpuppet.boards.host import host
from socpuppet.boards.ssd import add_ssd

board = host(drive_blocks=4096, drive=add_ssd)
board.platform.build()
board.platform.load_elf("build/host/zephyr/zephyr.elf", via=board.cpu.socket)
board.platform.load_elf("build/ssd/zephyr/zephyr.elf", via=board.drive.ssd.cpu.socket)

board.platform.run(sp.ms(1000))
print(board.uart.output)                        # the host's console
print(board.drive.ssd.cpu_kit.uart.output)      # the SSD's
```

`examples/host_and_ssd_hello.py` is that with Zephyr's disk test for the host, and it prints the two consoles as one story, each line with the time it was said:

```text
ms     who   said
3.2    ssd   *** Booting Zephyr OS build v4.4.2 ***
3.9    ssd   socpuppet SSD firmware: a drive of 512 pages of 4096 bytes
137.2  host  *** Booting Zephyr OS build v4.4.2 ***
137.5  host  Running TESTSUITE disk_driver
138.6  host  Disk reports 4096 sectors
```

- ⚠️ **Say whose, every time.** There are two CPUs, so `load_elf`, `peek32`, `poke32` and `devicetree` each want `via=`, and say so if it is left out. `via=board.cpu.socket` is the host's view and `via=board.drive.ssd.cpu.socket` the SSD's. The same address is two different things in the two: [the address map](address-map.md#the-host-with-the-ssd) has both.
- ⚠️ **Load both images.** An SSD with nothing loaded never says it is ready, and the host waits for it with nothing on its console. What you do see is the log filling with `[W] ssd.bus : target address=0x0 not found for read transaction`: a CPU with no program is busy, not idle, and it is running whatever its empty memory holds. That also makes the run slow to give up, a minute or two of wall time for two seconds of simulated time.
- **Both CPUs start together, and the host waits for its drive.** The SSD's firmware is ready 4 ms in with a 2 MiB drive, and 0.27 s in with a 2 GiB one, because it starts by making a table of every page. A host must not assume the drive is ready when it gets there. Zephyr's NVMe driver does it properly: the drive says in its `CAP.TO` register how long a host should give it, one second for this SSD, and the driver gives it that and half a second more. A driver of your own should read it too.
- 💡 **One clock, and the same story every time.** Both CPUs are in one simulation, so a run is deterministic: run it twice and every line comes at the same simulated time. A bug that needs the two firmwares to be in step by luck will be there again tomorrow.
- 🎓 **Each CPU runs ahead a little, then lets the other catch up.** That stretch is the *quantum*, 100 µs by default, and it is what makes two CPUs fast: thirty times faster than taking turns after every instruction. The cost is that a CPU sees an interrupt up to a quantum late, and this run comes out 3% longer in simulated time. `board.platform.quantum = sp.us(10)` before `build()` trades speed for timing, and `0` is exact and slow.
- 🎭 **Take the SSD's firmware out when it is not what you are working on.** `drive=functools.partial(add_ssd, firmware=scripted_firmware().script)` is the SSD's hardware with a Python script for its firmware and no second CPU, and leaving `drive` out is the stand-in drive. The host's image is the same for all three.
- `tests/python/test_host_and_ssd_firmware_together.py` is a complete example.

## The SSD under this machine's Linux

🐧 The SSD's host can be the machine the simulation runs on. `ssd(host=this_machine)` puts [`sp.PciemHost`](models/pciem-host.md) where the scripted host goes, and it puts the drive on this machine's own PCIe bus through pciem, a Linux kernel module: Linux's own `nvme` driver binds it, `lsblk` lists it, and `mkfs.ext4` and `mount` use it, while the SSD's firmware runs in the simulation. It takes a build with pciem, on a Linux machine with pciem loaded ([setup.md](setup.md#6-pciem-optional)).

```sh
PYTHONPATH=python uv run python -m socpuppet drive              # the SSD with its Zephyr firmware, 64 MiB
PYTHONPATH=python uv run python -m socpuppet drive --firmware behavioral --blocks 2048
```

It says where the drive is under `/sys/bus/pci/devices`, and runs until Ctrl-C. From Python:

```python
from socpuppet.boards.real_host import this_machine
from socpuppet.boards.ssd import ssd
from socpuppet.pump import pump

board = ssd(host=this_machine, blocks=131072)
board.platform.build()
board.platform.load_elf("build/ssd/zephyr/zephyr.elf", via=board.ssd.cpu.socket)
board.host.start()
pump(board.platform, far_ends=[board.host], until=lambda: done)
```

- 🧵 **Pump it.** From `start()` on, Linux is talking to the drive, and the drive answers only while its platform runs. `socpuppet.pump.pump` runs it on the wall's time and keeps up with what Linux writes.
- ⚠️ **Find it by where it is.** The puppet's drive is the one under pciem's bus, `socpuppet.boards.real_host.puppet_function()`. On a machine with NVMe drives of its own it is not `nvme0n1`.
- ⚠️ **Let Linux go before the platform ends**: unbind its driver while the platform still runs, or each command Linux was owed costs half a minute as the program ends ([pciem-host.md](models/pciem-host.md#what-it-does)). Unbinding shuts the drive down, which has the firmware save its table, so what was written can be read back out of the NAND.
- 🎭 `socpuppet.boards.real_host.behavioral_drive(blocks=)` is the stand-in drive in front of this machine's Linux, with no CPU.
- `tests/python/test_this_machines_linux_mounts_the_ssd.py` is a complete example: Linux formats and mounts the SSD, writes a file, and Python reads it back from the NAND.

## The host across the link

The host's two dies have 🎭 a stand-in between them by default, a link that is always up and passes everything straight through. The real one, [`sp.D2dLink`](models/d2d-link.md), carries nothing until it has been trained, and its end on the compute die holds the host's CPU in reset. So a host with the real link needs someone to train it: the IO die's manager. Hand `host` the function that describes one, and the link is the real one:

```python
import functools

import socpuppet as sp
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager, scripted_manager

a_scripted_manager = functools.partial(add_manager, script=scripted_manager().script)

board = host(manager=a_scripted_manager)
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf", via=board.cpu.socket)

board.platform.run(sp.ms(100))
print(board.uart.output)
```

Nothing is built differently for it. The image is the one from [the host's first step](boot-your-firmware.md#1-build-the-firmware), and with `drive_blocks=` and `drive=` as well it is the one built with the shield. The host's firmware cannot tell which link it has: the devicetree its CPU sees is the same with either, and a test holds it so.

`examples/chiplet_host_hello.py` is that with Zephyr's `hello_world`. It prints the link's bring-up out of the trace, and then the host's console:

```text
ms     from         packet
4.000  io.d2d       {SBINIT Out of Reset}
...
4.750  compute.d2d  {LinkMgmt.RDI.Rsp.Active}
5.000  io.d2d       MemoryWrite_32b 0x24 = 0x0
5.000  compute.d2d  Completion, success

*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_host/socpuppet_rv64
```

- 🎭 **The manager is a script here.** `scripted_manager().script` is [`sp.IoManager`](models/io-manager.md) told where the link's registers are, and it does what the firmware of [the IO die's manager](#the-io-dies-manager) does, in the same order. That firmware, on a CPU of its own under this host, is [the whole cast](#the-whole-cast-three-firmwares) below.
- ⚠️ **The host's first instruction is 5 ms late.** UCIe holds a link in reset for 4 ms after power-on, training takes this link a millisecond more, and only then does the manager let the host go. A time limit that was tight for the stand-in link is 5 ms too tight for this one.
- ⚠️ **Say whose.** The manager's script is a bus master too, so `load_elf`, `peek32` and `devicetree` want `via=board.cpu.socket`, and say so if it is left out.
- **Everything the host does on its IO die crosses the link**, a transaction at a time: every character it prints, every register of its drive, and coming back, every byte its drive moves in or out of the host's memory and every interrupt, which is a message. The host's own RAM, timer and interrupt controller are on its own die and cross nothing.
- 💡 **Watch it cross.** `host(manager=..., trace=True)` records every crossing in `board.platform.trace`, each with the port it left by: `compute.d2d.peer_initiator` for what the compute die sent and `io.d2d.peer_initiator` for what came back. ⚠️ An address in a record is the receiving die's own. What the compute die sends has had the start of its window taken off, so the UART is at `0x0` there and not at `0x1000_0000`. `sp.render_sideband(board.platform.trace)` is the link's own management traffic as a table, and `ucie.sideband_packets` the packets themselves.
- **It costs nothing you will notice.** Zephyr's disk test finishes 5 ms later than with the stand-in link, which is the late start and nothing more, and in the same wall time. ⚠️ That is not the whole truth about the link. A crossing takes [the link's](models/d2d-link.md) `latency_ns`, 20 ns by default, and its bytes at `bytes_per_ns`, and the host's CPU counts in whole cycles of 100 ns: a crossing of less than 200 ns does not show on its clock at all ([upstream.md](upstream.md) has why). The trace is where to look for the link's own timing. 🚧 `host()` has no way to be given a link of your own yet: copy the board to try a slow one.
- `tests/python/test_host_across_the_real_link.py` is a complete example: `hello_world`, Zephyr's disk test against all three drives, and what the trace shows of each command.

## The IO die's manager

The third board is `socpuppet_iomgr`: the management CPU on the IO die of a chiplet host, whose firmware brings the die-to-die link up and lets the compute die start. It is the same 32-bit RISC-V machine as the SSD's controller, with one device of its own.

| What | Where | Zephyr driver |
|---|---|---|
| CPU | RV32IMAC, machine mode, starts at `0x2000_0000` | |
| SRAM, which the firmware runs from | `0x2000_0000`, 256 KiB | |
| Scratch memory, for the other die to reach | `0x3000_0000`, 4 KiB | (a second `memory` node, `io_scratch`) |
| Machine timer | `0x0200_0000`, 10 MHz | `riscv,machine-timer` |
| Interrupt controller (PLIC) | `0x0C00_0000`, 31 sources | `sifive,plic-1.0.0` |
| UART, the console | `0x1000_0000` | `ns16550` |
| [Die-to-die link](models/d2d-link.md) | `0x1001_0000`, PLIC source 1 | `socpuppet,ucie-link`, a Zephyr reset controller |

```sh
west build -b socpuppet_iomgr samples/hello_world -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

The manager is never alone either: there is a compute die at the other end of the link, 🎭 a script here, which stays held in reset until the firmware lets it go.

```python
import socpuppet as sp
from socpuppet.boards.io_manager import io_manager, one_round_trip

board = io_manager(compute=one_round_trip)
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf", via=board.manager.cpu.socket)

board.platform.run(sp.ms(100))
print(board.manager.cpu_kit.uart.output)
```

`hello_world` boots and trains nothing, so the compute die never runs. Firmware that does the job is [`firmware/iomgr`](../firmware/iomgr/README.md), which is short enough to read whole:

```c
#include <zephyr/drivers/reset.h>
#include <socpuppet/drivers/ucie_link.h>

static const struct device *const link = DEVICE_DT_GET_ONE(socpuppet_ucie_link);

ucie_link_train(link);                                  /* sleeps until it is up */
reset_line_deassert(link, UCIE_LINK_THE_OTHER_DIE);     /* lets the other die go */
for (;;) {
	ucie_link_wait_until_down(link);                /* sleeps until it is not */
	ucie_link_retrain(link);
}
```

```text
*** Booting Zephyr OS build v4.4.2 ***
iomgr: training the D2D link
iomgr: D2D link up
iomgr: compute die released
```

- 🎓 **Letting the other die go is Zephyr's reset API**, because that is what it is: the other die's CPU is this link's one reset line. The register that holds it is at the *far* end of the link, so the driver reaches it over the link's sideband. `CONFIG_RESET=y` in `prj.conf` is what asks for the driver.
- ⚠️ **The link's interrupt is a level.** Its line stays high for as long as the status says it has changed, so the driver's handler clears that bit before it returns. A handler that only woke a thread would be called again at once, for ever, and the thread would never run. What changed is still there to read: whether the link is up.
- ⚠️ **A link takes 5 ms to come up, and 4 ms of that cannot be hurried.** UCIe holds a link in reset that long. Firmware that polled the status in a tight loop would wait just as long and learn nothing sooner.
- 💡 **Break the link to see the firmware mend it.** A second 🎭 scripted master on the IO die's bus can write the link's fault-injection register, as `tests/python/test_link_training.py` does. The firmware says `iomgr: the D2D link went down`, trains it again, and says it is up.
- `tests/python/test_zephyr_on_the_io_manager.py` and `tests/python/test_link_training.py` are complete examples, and `examples/io_manager_hello.py` is the same boot with 🎭 a script in the firmware's place and the link's whole handshake printed out.

## The whole cast: three firmwares

Everything above comes together in one description: the host across the real link, with the manager's own CPU to bring the link up and the SSD's own CPU to be its drive. Three CPUs, three images, one simulation. The host's image and the SSD's are the two built [above](#the-host-with-the-ssd), and the manager's is built the same way:

```sh
west build -d build/iomgr -b socpuppet_iomgr /path/to/socpuppet/firmware/iomgr -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

```python
import socpuppet as sp
from socpuppet import ztest
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import add_ssd

board = host(drive_blocks=4096, manager=add_manager, drive=add_ssd)
board.platform.build()
board.platform.load_elf("build/iomgr/zephyr/zephyr.elf", via=board.manager.cpu.socket)
board.platform.load_elf("build/host/zephyr/zephyr.elf", via=board.cpu.socket)
board.platform.load_elf("build/ssd/zephyr/zephyr.elf", via=board.drive.ssd.cpu.socket)

story = sp.Transcript(
    board.platform,
    {
        "manager": board.manager.cpu_kit.uart,
        "ssd": board.drive.ssd.cpu_kit.uart,
        "host": board.uart,
    },
)
story.run_until(
    lambda: any(line.who == "host" and ztest.verdict_of(line.text) for line in story.lines),
    timeout=sp.ms(2000),
)
print(sp.render_transcript(story.lines))
```

Nothing is built differently for it. Each image is the one that boots on its own board: `socpuppet_iomgr` for the manager, `socpuppet_host` with its shield for the host, `socpuppet_ssd` for the SSD. `examples/full_bootchain.py` is that with the manager's firmware of `firmware/iomgr`, Zephyr's disk test and the SSD's firmware of `firmware/ssd`, and it prints the link's bring-up before the story:

```text
ms     who      said
1.3    manager  *** Booting Zephyr OS build v4.4.2 ***
1.5    manager  iomgr: training the D2D link
3.2    ssd      *** Booting Zephyr OS build v4.4.2 ***
3.9    ssd      socpuppet SSD firmware: a drive of 512 pages of 4096 bytes
5.5    manager  iomgr: D2D link up
5.6    manager  iomgr: compute die released
142.7  host     *** Booting Zephyr OS build v4.4.2 ***
143.0  host     Running TESTSUITE disk_driver
144.1  host     Disk reports 4096 sectors
...
603.7  host     PROJECT EXECUTION SUCCESSFUL
```

- **The boot has an order, and the hardware fixes it.** The manager and the SSD start at power-on. The host cannot: the link's end on its die holds its CPU in reset until the manager's firmware has trained the link and let it go, 5.5 ms in. And the host cannot learn the size of its disk until the SSD's firmware is there to answer.
- 💡 **`sp.Transcript` is who said what, and when.** Give it the consoles by name. `story.run_until(condition, timeout)` runs the platform and listens as it goes, noting each whole line with who said it and the simulated time it was heard, and `sp.render_transcript` prints them as a table. A test can ask it about order: the time of the manager's `compute die released` against the time of the host's first line.
- ⚠️ **Two consoles heard at the same moment have no order.** Each CPU runs a quantum ahead before the others catch up, 100 µs by default, so lines that two firmwares print within one quantum are heard together. They get the same time and come out in the order the consoles were given. Compare times, not places in the list.
- ⚠️ **Say whose, every time, and load all three.** `via=board.manager.cpu.socket`, `via=board.cpu.socket`, `via=board.drive.ssd.cpu.socket`. A manager with no image never lets the host go, and the host prints nothing at all. An SSD with no image never says it is ready, and the host waits for it. Each also fills the log with `target address=0x0 not found`, the mark of a CPU running an empty memory.
- **The manager's firmware sees its own board, less the scratch memory.** Under the host the manager has a bus of its own with its kit and the link's registers on it, at the addresses `socpuppet_iomgr` has them ([the address map](address-map.md#the-host-across-the-link)). The scratch memory of that board was for 🎭 a compute die to reach, and the firmware never used it.
- 🎭 **Take out what you are not working on.** Each of the two functions has its stand-in, and the host's image is the same with any of them: `manager=functools.partial(add_manager, script=scripted_manager().script)` is a script for the manager, `drive=functools.partial(add_ssd, firmware=scripted_firmware().script)` a script for the SSD's firmware, and leaving `drive` out is the stand-in drive.
- **It costs nothing you will notice.** The manager's firmware lets the host go half a millisecond later than 🎭 the script does, the disk test's verdict comes that half millisecond later, at 603.7 ms of simulated time, and the wall time is the same as with the script: under half a second.
- `tests/python/test_full_bootchain.py` is a complete example.

## Booting from flash

Everything above wakes a CPU up with its firmware already in RAM, because `load_elf` put it there. 🎭 That is Python standing in for a boot ROM, and it is the quick way to try an image. Silicon has nobody to do that. A real CPU starts in a ROM, whose program finds the firmware in a flash, copies it into RAM and jumps to it. Every socpuppet board boots that way too, when it is asked to:

```python
import socpuppet as sp
from socpuppet import boot_image
from socpuppet.boards.boot import from_rom
from socpuppet.boards.host import host

board = host(boot=from_rom)
board.platform.build()
# The ROM's own program goes in the ROM.
board.platform.load_elf("build/firmware/rom_rv64.elf", via=board.cpu.socket)
# The firmware goes in the flash, wrapped, where the ROM will look.
board.platform.poke(
    board.syscon.component.boot_address,
    boot_image.wrap("build/host/zephyr/zephyr.elf"),
    via=board.cpu.socket,
)
board.platform.run_until(lambda: "Hello World!" in board.uart.output, timeout=sp.ms(200))
print(board.uart.output)
```

```text
rom: zephyr: 12104 bytes to 0x80000000, jumping to 0x80000000
*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_host/socpuppet_rv64
```

The first line is the ROM's, and nothing was in RAM before it.

### Two ways to boot

| | 🎭 The quick way | From the ROM |
|---|---|---|
| Describe the board | `host()` | `host(boot=from_rom)` |
| The CPU starts in | RAM, at `0x8000_0000` | [the ROM](models/rom.md), at `0x1000` |
| You load | the firmware, into RAM: `load_elf` | the ROM's program into the ROM (`load_elf`), and the firmware's [boot image](models/boot-image.md) into [the flash](models/spi-flash.md) (`poke` or `load_binary`) |
| The firmware greets at | 1 ms | 25.6 ms |
| A reset | starts the CPU in a RAM nobody reloads | loads the image again |
| Use it | to try an image, and to boot something big | to test what a boot really does: the order, the flash, a bad image, a watchdog |

Nothing is built differently. The two ways show firmware the same devicetree, so the image that boots one way boots the other.

- **The ROM is `firmware/rom`**, a start in assembly and two pages of C with no Zephyr in it. `firmware/build.py` builds it for each kind of CPU: `rom_rv64.elf` for the host, `rom_rv32.elf` for the SSD and the manager. [Its README](../firmware/rom/README.md) has every line it can say.
- 🎓 **A boot image is the ELF file with the reading done.** A ROM of a kilobyte cannot read ELF, so `boot_image.wrap(file)` lays the program out as it will be in memory and puts a header of 72 bytes in front: a name, which kind of CPU, where the bytes go, where to start, a CRC, and an argument for the program. `socpuppet boot-image zephyr.elf -o zephyr.img` writes one to a file, and `platform.load_binary("zephyr.img", at=..., via=...)` loads it.
- **Where the image goes is the system controller's `boot_address`.** Each CPU's ROM asks [its system controller](models/system-controller.md) where to look. For the host that is the start of the flash, `0x1020_0000`. The IO die's manager shares that flash and looks 2 MiB further in. So ask the board, as above, and do not write the address down.
- **The flash is across the link.** The host's flash is on the IO die, so every byte of the image crosses the die-to-die link on its way to RAM. With `trace=True` the reads are in the trace, which `examples/boot_from_flash.py` counts.
- ⚠️ **A ROM checks what it loaded, and that takes time.** The copy of Zephyr's `hello_world` is 1.5 ms and the CRC of it 23 ms: the sum is worked out half a byte at a time, which is what a ROM of this size can afford. It is the honest price of booting as silicon does, and the reason the quick way is the default.
- **A bad image is a sentence on the console**, and nothing is started: `rom: no image at 0x10200000` for an empty flash, `rom: zephyr: bad CRC: ...` for bytes that are not the ones the header was made for, `rom: zephyr is a 32-bit image, and this is a 64-bit CPU`, and `rom: stopped by a trap: ...` for an image with nowhere to go.
- ⚠️ **`load_elf` of the firmware is refused on a board with a ROM**, and the error says where the image goes instead. What a CPU is given by `load_elf` has to start where the CPU does, and that is now the ROM.
- **All three CPUs can.** `host(boot=from_rom, manager=functools.partial(add_manager, boot=from_rom), drive=functools.partial(add_ssd, boot=from_rom))` is three ROMs and two flashes, the IO die's holding the host's image and the manager's, and the SSD's its own. Each is loaded through its own CPU, at its own system controller's `boot_address`. Or mix them: a board can boot one CPU from its ROM and load another the quick way.
- `tests/python/test_rom_boot.py` is a complete example, and `tests/python/cast.py` has the loading for three CPUs in one function.

## Booting OpenSBI

🧦 [OpenSBI](https://github.com/riscv-software-src/opensbi) is the machine-mode firmware a RISC-V kernel sits on, and the host boots it the way a server does. 🎓 SBI, the Supervisor Binary Interface, is how a program in supervisor mode asks machine mode for what only machine mode can do: set the timer, write to the console before it has a driver, reset the machine. OpenSBI's `fw_jump` is told two things as it starts, the hart's number in `a0` and the address of a devicetree in `a1`, and it jumps to whatever is 2 MiB into RAM. `firmware/build.py` builds it, with its own `test_payload` and one of ours, `sbi_payload`.

```python
import socpuppet as sp
from socpuppet import devicetree, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.host import RAM_BASE, host

board = host(boot=from_rom, sbi=True)
layout = opensbi.lay_out(
    open("build/firmware/fw_jump.bin", "rb").read(),
    open("build/firmware/test_payload.bin", "rb").read(),
    devicetree.compile(
        board.platform.devicetree(dialect="linux", model="socpuppet host")
    ),
    ram=RAM_BASE,
)
board.platform.build()
opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)
board.platform.run_until(
    lambda: "Test payload running" in board.uart.output, timeout=sp.ms(3000)
)
print(board.uart.output)
```

```text
OpenSBI v1.9
   ____                    _____ ____ _____
  ...
Platform Name               : socpuppet host
Platform Timer Device       : aclint-mtimer @ 10000000Hz
Platform Console Device     : uart8250
Platform Reboot Device      : syscon-reboot
Platform Shutdown Device    : syscon-poweroff
  ...
Boot HART ISA Extensions    : smaia,zicntr,smcsrind,f,d
Boot HART PMP Count         : 0
  ...
Test payload running
```

What is different from booting Zephyr:

- **`sbi=True` describes the host for a monitor**, with an operating system below it. Neither OpenSBI nor Linux says where an APLIC that serves supervisor mode sends its messages, so with it both APLICs are built knowing: the IMSIC's page for supervisor mode ([aplic.md](models/aplic.md)).
- **The devicetree is in Linux's dialect**, `dialect="linux"`, which OpenSBI reads and hands on. It names the board after `model`, gives a command line in `chosen` when it is given `bootargs`, and has the nodes OpenSBI looks for: one IMSIC node for each mode, a `syscon-reboot` and a `syscon-poweroff`, an ACLINT timer. `socpuppet devicetree --dialect linux <file>` prints it. OpenSBI reads the blob, which `devicetree.compile` makes with `dtc`.
- 🎭 **The quick way puts QEMU's reset vector in the ROM.** `fw_jump` wants two registers set, and nothing outside a CPU can set them, so `opensbi.load` puts six instructions in the ROM that do (`boot.reset_stub`), as QEMU's `virt` machine has at the same address. The ROM still has to be there: `host(boot=from_rom)`.
- **From the flash**, `opensbi.flash_image(layout)` is the whole layout as one boot image, its argument the devicetree's address, which the ROM hands on in `a1`. It is 2 MiB of zeros and a little more, which the ROM checks in about four seconds of the CPU's time, three on the clock on the wall.
- **About a second of the CPU's time** passes before the payload runs: most of it is OpenSBI's banner, a character at a time through a UART on the other die. The wall clock says about the same.
- ⚠️ **A reboot from the quick way does not come back.** Nothing loads RAM again, and `fw_jump` started a second time finds its choice of which hart boots already made. To see a reboot, boot from the flash, where the ROM copies OpenSBI afresh.
- `tests/python/test_opensbi_boots.py` boots both ways, with OpenSBI's payload and with ours, which takes a timer interrupt, has a misaligned load made for it, reboots once and is then switched off.

## Booting UEFI

🧦 [EDK2](https://github.com/tianocore/edk2) is UEFI, the firmware a PC or a server loads its kernel with, and its RISC-V port runs on OpenSBI where a kernel would: in supervisor mode, 2 MiB into RAM, with the hart's number in `a0` and the devicetree in `a1`. 🎓 It boots in phases. **SEC** sets up a stack and unpacks the rest; **DXE** loads a few dozen drivers, each saying so on the console; and **BDS**, the boot manager, finds nothing to boot and starts the **UEFI shell**, which takes commands at `Shell>`. On the way it turns paging on and takes the timer's interrupt in supervisor mode, which makes it the first program here not written for the puppet to do either. `firmware/build.py` builds it as `uefi.fd`, QEMU's port of it built for where `fw_jump` jumps.

```python
import re

import socpuppet as sp
from socpuppet import devicetree, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.host import RAM_BASE, host

board = host(boot=from_rom, sbi=True)
layout = opensbi.lay_out(
    open("build/firmware/fw_jump.bin", "rb").read(),
    open("build/firmware/uefi.fd", "rb").read(),
    devicetree.compile(
        board.platform.devicetree(dialect="linux", model="socpuppet host")
    ),
    ram=RAM_BASE,
)
board.platform.build()
opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)
board.platform.run_until(
    lambda: "Shell>" in board.uart.output, timeout=sp.ms(150_000)
)

said = len(board.uart.output)
board.uart.write("ver\r")
board.platform.run_until(
    lambda: "Shell>" in board.uart.output[said:], timeout=sp.ms(10_000)
)
# The console is a terminal: take out its colours and cursor moves.
print(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", board.uart.output))
```

```text
OpenSBI v1.9
  ...
SecStartupPlatform() BootHartId: 0x0, DeviceTreeAddress=0x82200000
  ...
Loading driver at 0x00082DD2000 EntryPoint=0x00082DD227C DevicePathDxe.efi
  ...
RiscVConfigureMmu: SATP mode 8 successfully configured
  ...
Press ESCAPE within 5 seconds for boot options
  ...
UEFI Interactive Shell v2.2
EDK II
UEFI v2.70 (EDK II, 0x00010000)
  ...
Press ESC in 1 seconds to skip startup.nsh or any other key to continue.
Shell> ver
UEFI Interactive Shell v2.2
EDK II
UEFI v2.70 (EDK II, 0x00010000)
Shell>
```

What is different from booting OpenSBI's payloads:

- **It takes a minute of the CPU's time.** About 66 s on the interpreter and 87 on QBox, which is 44 s and 2 s on the wall of a quick machine. Half of it is SEC unpacking the rest of EDK2, 6 MB compressed with LZMA, and 10 s of it is two countdowns of 5 s, the boot manager's and the shell's, each waiting for a key, asleep between the timer's interrupts. 550 million instructions in all: [speed-spike.md](history/speed-spike.md#a-boot-that-ran-opensbi-and-uefi-to-the-shell-m28) has them by phase.
- **Paging goes on in the hart's biggest mode.** EDK2 writes Sv57, Sv48 and Sv39 to `satp` in turn and keeps the first that reads back: mode 8, Sv39, on DBT-RISE's hart, and mode 10, Sv57, on QBox's.
- 🧵 **Type at it as at Zephyr's shell**, with `board.uart.write`, and Enter is `"\r"`. The console is a terminal, so `uart.output` has escape sequences in it for colour and the cursor, which the example takes out. `memmap` lists every region of the 64 MiB the devicetree gave, OpenSBI's own at the start marked reserved, and takes 22 s of the interpreter's time to print.
- **`reset` reboots**, through SBI's reset call to the system controller. From the flash the ROM copies the image again and the boot starts over; the quick way does not come back, as with OpenSBI.
- **From the flash** it is `opensbi.flash_image(layout)`, as with OpenSBI: `fw_jump`, the 2 MiB to where it jumps, the 2 MiB of EDK2 and the devicetree, 4.2 MB, which the ROM checks in about 9 s of the CPU's time. The boot flash is 16 MiB, so it fits before the manager's image.
- **Its variables are kept in RAM** and forgotten at reset: there is no flash UEFI can write them to. The boot manager registers the shell as a boot option again at each boot, so nothing is lost that a test needs.
- ⚠️ **A line of exclamation marks for most drivers it loads**, `Image Section Alignment(0x40) does not match Required Alignment (0x1000)`, is EDK2's own build for RISC-V, which links its modules with sections too close together to protect. The boot is unaffected ([upstream.md](upstream.md)).
- **Nothing of the AIA.** EDK2 has no driver for the APLIC or the IMSIC, so its console is polled and its only interrupt is the timer's.
- `tests/python/test_uefi_boots.py` boots both ways, types `ver` and `memmap`, and resets from the flash.

## Booting Linux

🐧 A stock Linux kernel boots on OpenSBI the way UEFI does, 2 MiB into RAM with the devicetree in `a1`, with its root filesystem on 🎭 the virtio disk and its console on the virtio console; and through UEFI too, from a disk cut up as a server's. `socpuppet linux` boots it with your terminal at its console. [linux.md](linux.md) has the boot, typing at its shell yourself or from Python, the virtio cast under Linux's drivers, a shared directory, and what to do when it does not boot.

## When the watchdog bites

Every socpuppet CPU has a [watchdog](models/watchdog.md) and a [system controller](models/system-controller.md), and Zephyr drives both with drivers of its own. 🎓 A watchdog is a counter that resets the CPU when it runs out, and firmware keeps it from running out by feeding it. Firmware that hangs stops feeding, and the reset puts it back on its feet. The system controller then says why the CPU was reset, which is how firmware knows that it happened.

```c
#include <zephyr/drivers/syscon.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/sys/reboot.h>
#include <socpuppet/regs/system_controller.h>

static const struct device *const system_controller =
	DEVICE_DT_GET_ONE(socpuppet_system_controller);
static const struct device *const watchdog = DEVICE_DT_GET_ONE(sifive_wdt);

uint32_t cause;
syscon_read_reg(system_controller, SYSTEM_CONTROLLER_RESET_CAUSE, &cause);

const struct wdt_timeout_cfg timeout = {
	.window.max = 90, /* milliseconds */
	.flags = WDT_FLAG_RESET_SOC,
};
int channel = wdt_install_timeout(watchdog, &timeout);
wdt_setup(watchdog, 0);
/* ...and then, more often than every 90 ms: */
wdt_feed(watchdog, channel);
```

```ini
CONFIG_WATCHDOG=y
CONFIG_SYSCON=y
CONFIG_REBOOT=y
```

`firmware/watchdog` is a whole application of that, which gets itself reset twice and says why each time it starts. `examples/boot_from_flash.py` boots it from the host's flash:

```text
ms     who   said
29.0   host  rom: watchdog_socpuppet_host: 14448 bytes to 0x80000000, jumping to 0x80000000
30.2   host  reset cause: power-on
60.6   host  watchdog: ran out, and interrupted
89.6   host  rom: watchdog_socpuppet_host: 14448 bytes to 0x80000000, jumping to 0x80000000
90.8   host  reset cause: software
121.3  host  watchdog: fed 1
...
273.5  host  watchdog: fed 6
273.7  host  watchdog: no more feeding
392.5  host  rom: watchdog_socpuppet_host: 14448 bytes to 0x80000000, jumping to 0x80000000
393.8  host  reset cause: watchdog
```

- **`RESET_CAUSE` reads `POWER_ON`, `SOFTWARE` or `WATCHDOG`**, by the names in `<socpuppet/regs/system_controller.h>`. It is the one thing that survives a reset, which is why it is in a register and not in the firmware's memory.
- **`sys_reboot()` works.** Zephyr leaves its last step to the SoC, and socpuppet's SoC writes the system controller's `RESET_REQUEST`. Turn on `CONFIG_REBOOT`.
- **A watchdog can interrupt and not reset**: `WDT_FLAG_RESET_NONE` with a `callback`. The interrupt is a wire to the interrupt controller on the watchdog's own die: the compute die's APLIC on the host, the PLIC on the SSD and the manager.
- ⚠️ **Boot from the ROM for this.** The quick way does not survive a reset. The CPU starts again in a RAM nobody reloads, with the firmware's data as the first run left it, and Zephyr takes a fault before it gets to `main`. A reset needs something to put the image back, which is what the ROM and the flash are for.
- ⚠️ **A reset reaches the CPU and nothing else.** The interrupt controllers and every other device are left as they were, as on many real chips whose watchdog resets the core alone. Zephyr's drivers set up what they use, so it comes up. Firmware that trusts a device to be as it was at power-on would be wrong here.
- **A watchdog that has bitten is off**, and at zero, as it is at power-on: that much it does for itself. After a reset the firmware asked for it is still running as it was set up, and firmware that starts again feeds it or sets it up again.
- ⚠️ **Zephyr cannot switch this watchdog off.** `wdt_disable()` on SiFive's watchdog gives it its longest period, about eighteen hours, and leaves it running ([watchdog.md](models/watchdog.md)).
- `tests/python/test_rom_boot.py` holds all of it, on the host and on the SSD.

## Debugging three CPUs at once

Each CPU of a board can have a port of its own, and a GDB each:

```python
import functools

import socpuppet as sp
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import add_ssd

board = host(
    gdb_port=1234,
    drive_blocks=4096,
    manager=functools.partial(add_manager, gdb_port=1235),
    drive=functools.partial(add_ssd, gdb_port=1236),
)
board.platform.build()
board.platform.load_elf("build/iomgr/zephyr/zephyr.elf", via=board.manager.cpu.socket)
board.platform.load_elf("build/host/zephyr/zephyr.elf", via=board.cpu.socket)
board.platform.load_elf("build/ssd/zephyr/zephyr.elf", via=board.drive.ssd.cpu.socket)
board.platform.run(sp.ms(1000))     # waits here until each GDB has said continue
```

Then, each in a terminal of its own:

```sh
riscv64-zephyr-elf-gdb -ex "set remotetimeout 600" -ex "target remote :1235" build/iomgr/zephyr/zephyr.elf
riscv64-zephyr-elf-gdb -ex "set remotetimeout 600" -ex "target remote :1236" build/ssd/zephyr/zephyr.elf
riscv64-zephyr-elf-gdb -ex "set remotetimeout 600" -ex "target remote :1234" build/host/zephyr/zephyr.elf
```

The same GDB program debugs both kinds of CPU: each server tells its debugger whether its core is 32-bit or 64-bit. Any one or two of the ports can be left out, and a CPU without one runs without waiting for anybody.

- ⚠️ **A stopped CPU stops the world.** The simulation has one thread, and a CPU stopped in its debugger keeps it. So while one CPU sits at a breakpoint the other two are frozen with it, at whatever instruction they had reached, and simulated time stands still. Nothing runs on behind your back, which is what makes a session with three CPUs repeatable. It is not how a board on a bench behaves, where the other two would carry on and time out.
- ⚠️ **`set remotetimeout`, before `target remote`.** A GDB reads memory as it attaches, and it is answered only while its own CPU is the one that is stopped. The CPUs stop one at a time, each when the one before has been told to continue, so a GDB waits for its turn, and gives up after two seconds unless it is told to be patient. The time it is given is yours to spend: ten minutes here, in which to set breakpoints in the first GDB and continue it. Or attach each GDB only when you are ready to let the one before it go.
- **Each CPU has to be told to continue once**, because each stops before its first instruction. The manager's and the SSD's stop at power-on, a picosecond in: a CPU with a debugger waits that long, the smallest step of time, for a reset that may still be on its way through the board. The host's stops at 5.5 ms, when the link lets it go, which cannot come until the manager's is running.
- **Look at one CPU at a time.** While one CPU is at a breakpoint, another's GDB gets no answer about memory, so `x` and `backtrace` there wait until the stopped one continues. To see what the SSD is doing while the host waits for it, set a breakpoint in the SSD's firmware and continue the host.
- 💡 **`monitor sysc print_time` asks a CPU the simulated time.** At a breakpoint it says when in the boot you are, on the clock all three share.
- **Two CPUs cannot share a port**, and a platform says so by name when it is built.
- `tests/python/test_gdb.py` drives three debuggers from one test, with a small client of its own in place of GDB.
