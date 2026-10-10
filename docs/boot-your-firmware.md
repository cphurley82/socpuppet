# Boot your firmware here 🧦

How to run a Zephyr application on one of socpuppet's boards: the host, [the SSD's controller](#the-ssds-controller) or [the IO die's manager](#the-io-dies-manager), and how to run [the host's firmware and the SSD's together](#the-host-with-the-ssd). The steps are the host's, and each other section says what differs. You need Python 3.12 or newer and a Zephyr workspace with the Zephyr SDK. socpuppet is tested with Zephyr 4.4.2 and SDK 1.0.1.

🚧 socpuppet is not on PyPI yet. Until it is, "install" means building it from a checkout: see [development.md](development.md).

## The board

The board is called `socpuppet_host`. It is a 64-bit RISC-V machine:

| What | Where | Zephyr driver |
|---|---|---|
| CPU | RV64IMAC, machine mode, starts at `0x8000_0000` | |
| RAM | `0x8000_0000`, 64 MB | |
| Interrupt controller (PLIC) | `0x0C00_0000`, 31 sources | `sifive,plic-1.0.0` |
| UART, the console | `0x1000_0000` | `ns16550` |
| Machine timer | `0x0200_0000`, 10 MHz | `riscv,machine-timer` |

💡 You do not have to copy this table anywhere. The board's devicetree is generated from the platform description, so Zephyr already knows all of it. `socpuppet address-map python/socpuppet/boards/host.py` prints the map straight from that description, and [the address map](address-map.md) has every board's.

## 1. Tell Zephyr where the board is

The board lives in a Zephyr module inside the socpuppet package. One command prints where:

```sh
socpuppet zephyr-module
```

## 2. Build

Hand that directory to the build, and name the board:

```sh
west build -b socpuppet_host samples/hello_world -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

The image is `build/zephyr/zephyr.elf`.

## 3. Run

```python
import socpuppet as sp
from socpuppet.boards.host import host

board = host()
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf")

board.platform.run(sp.ms(100))      # 100 ms of simulated time
print(board.uart.output)
```

```text
*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_host/socpuppet_rv64
```

Or, for a first look, `python -m socpuppet.boards.host build/zephyr/zephyr.elf` does the same.

## With a drive

The host can have an SSD on a PCIe link: 🎭 the [behavioral NVMe](models/behavioral-nvme.md) behind a [PCIe endpoint](models/pcie-endpoint.md). Zephyr finds it by scanning the bus and uses it through its own NVMe driver and its disk API (`disk_access_read` and friends, on the disk `nvme0n0`).

| What | Where | Zephyr driver |
|---|---|---|
| PCIe root complex, configuration window | `0x1010_0000`, one bus | `socpuppet,pcie`, from socpuppet's module |
| PCIe root complex, memory window | `0x1080_0000`, 1 MB | |
| MSI-to-PLIC bridge | `0x0300_0000`, to PLIC sources 1 and 2 | (the root complex's driver uses it) |
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

`tests/python/test_m3b_exit.py` is a complete example. It runs Zephyr's own test of its disk interface, unchanged.

💡 The same image runs against the real SSD, with firmware of its own behind it: see [The host with the SSD](#the-host-with-the-ssd).

⚠️ Firmware built with the shield needs the drive. On a host described without one it stops before it prints anything: the first place it looks for the drive is an address where nothing answers.

💡 A PCIe device interrupts with a message, and the board's interrupt controller only has wires. [The bridge's page](models/msi-plic-bridge.md) says how the two meet.

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
- `tests/python/test_m4b_exit.py` is a complete example.

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
- 💡 **Switch on the log** (`CONFIG_LOG=y` and `CONFIG_LOG_MODE_MINIMAL=y`). A driver that cannot start says why there, in a line that starts `E:`, and without it all firmware can find out is that the device is not ready.
- **Hold it to the tests.** `tests/python/test_ssd_firmware.py` is what a host may expect of an SSD's firmware, a behaviour a test, and it runs whatever `ssd_socpuppet_ssd.elf` it finds in `SOCPUPPET_FIRMWARE_DIR`. Put your image there under that name and see how far it gets.
- 🎭 **Or do without the CPU.** [`sp.SsdFirmware`](models/ssd-firmware.md) is the same firmware as a Python script, for when the SSD's firmware is not what you are working on.

## The host with the SSD

Both boards above, in one simulation: the host's CPU runs the host's firmware, and its SSD's CPU runs the SSD's. Nothing is built differently for it. The host cannot tell the SSD from 🎭 the stand-in drive, and the SSD cannot tell a CPU from 🎭 a scripted host, so each image is the one you already have:

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
- 🎭 **Take the SSD's firmware out when it is not what you are working on.** `drive=functools.partial(add_ssd, firmware=stand_in_firmware().script)` is the SSD's hardware with a Python script for its firmware and no second CPU, and leaving `drive` out is the stand-in drive. The host's image is the same for all three.
- `tests/python/test_m6_exit.py` is a complete example.

## The host across the link

The host's two dies have 🎭 a stand-in between them by default, a link that is always up and passes everything straight through. The real one, [`sp.D2dLink`](models/d2d-link.md), carries nothing until it has been trained, and its end on the compute die holds the host's CPU in reset. So a host with the real link needs someone to train it: the IO die's manager. Hand `host` the function that describes one, and the link is the real one:

```python
import functools

import socpuppet as sp
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager, stand_in_manager

a_scripted_manager = functools.partial(add_manager, script=stand_in_manager().script)

board = host(manager=a_scripted_manager)
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf", via=board.cpu.socket)

board.platform.run(sp.ms(100))
print(board.uart.output)
```

Nothing is built differently for it. The image is the one from step 2, and with `drive_blocks=` and `drive=` as well it is the one built with the shield. The host's firmware cannot tell which link it has: the devicetree its CPU sees is the same with either, and a test holds it so.

`examples/chiplet_host_hello.py` is that with Zephyr's `hello_world`. It prints the link's bring-up out of the trace, and then the host's console:

```text
   4000.000 us       io ─▶ {SBINIT Out of Reset}
   ...
   4750.000 us  compute ─▶ {LinkMgmt.RDI.Rsp.Active}
   5000.000 us       io ─▶ MemoryWrite_32b 0x24 = 0x0
   5000.000 us  compute ─▶ Completion, success

*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_host/socpuppet_rv64
```

- 🎭 **The manager is a script here.** `stand_in_manager().script` is [`sp.IoManager`](models/io-manager.md) told where the link's registers are, and it does what the firmware of [the IO die's manager](#the-io-dies-manager) does, in the same order. 🚧 That firmware, on a CPU of its own under this host, is the next milestone's: three images in one simulation.
- ⚠️ **The host's first instruction is 5 ms late.** UCIe holds a link in reset for 4 ms after power-on, training takes this link a millisecond more, and only then does the manager let the host go. A time limit that was tight for the stand-in link is 5 ms too tight for this one.
- ⚠️ **Say whose.** The manager's script is a bus master too, so `load_elf`, `peek32` and `devicetree` want `via=board.cpu.socket`, and say so if it is left out.
- **Everything the host does on its IO die crosses the link**, a transaction at a time: every character it prints, every register of its drive, and coming back, every byte its drive moves in or out of the host's memory and every interrupt, which is a message. The host's own RAM, timer and interrupt controller are on its own die and cross nothing.
- 💡 **Watch it cross.** `host(manager=..., trace=True)` records every crossing in `board.platform.trace`, each with the port it left by: `compute.d2d.peer_initiator` for what the compute die sent and `io.d2d.peer_initiator` for what came back. ⚠️ An address in a record is the receiving die's own. What the compute die sends has had the start of its window taken off, so the UART is at `0x0` there and not at `0x1000_0000`. `ucie.sideband_packets(board.platform.trace)` reads the link's own management traffic back.
- **It costs nothing you will notice.** Zephyr's disk test finishes 5 ms later than with the stand-in link, which is the late start and nothing more, and in the same wall time. ⚠️ That is not the whole truth about the link. A crossing takes [the link's](models/d2d-link.md) `latency_ns`, 20 ns by default, and its bytes at `bytes_per_ns`, and the host's CPU counts in whole cycles of 100 ns: a crossing of less than 200 ns does not show on its clock at all ([upstream.md](upstream.md) has why). The trace is where to look for the link's own timing. 🚧 `host()` has no way to be given a link of your own yet: copy the board to try a slow one.
- `tests/python/test_m7_exit.py` is a complete example: `hello_world`, Zephyr's disk test against all three drives, and what the trace shows of each command.

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
- 💡 **Break the link to see the firmware mend it.** A second 🎭 scripted master on the IO die's bus can write the link's fault-injection register, as `tests/python/test_m5_exit.py` does. The firmware says `iomgr: the D2D link went down`, trains it again, and says it is up.
- `tests/python/test_m5b_exit.py` and `tests/python/test_m5_exit.py` are complete examples, and `examples/io_manager_hello.py` is the same boot with 🎭 a script in the firmware's place and the link's whole handshake printed out.

## Waiting for something to happen

A test usually wants to run until the firmware says something, with a limit in case it never does:

```python
booted = board.platform.run_until(
    lambda: "Hello World!" in board.uart.output,
    timeout=sp.ms(50),
)
assert booted, board.uart.output
```

⚠️ Give `run` a duration, or `run_until` a timeout. With no limit a run ends when nothing is left to do, and firmware with a timer running always has something left to do.

In pytest, mark each test that builds a platform with `@pytest.mark.platform`. A process can hold only one simulation, and the marker gives the test a process of its own. `tests/python/test_m3a_exit.py` is a complete example.

## Looking inside

- `board.platform.peek32(address)` and `poke32(address, value)` read and write memory the way a debugger does, without the firmware noticing.
- `board.platform.time` is the simulated time, in picoseconds. `sp.ms(1)`, `sp.us(1)` and `sp.ns(1)` make durations.
- `board.platform.devicetree()` is the devicetree the board was generated from.
- On a board with two CPUs, `peek32`, `poke32` and `devicetree` take `via=`, the CPU whose view you mean: `board.platform.peek32(address, via=board.drive.ssd.cpu.socket)`.

## Debugging with GDB

Give the board a port, and the CPU waits for a debugger before it executes anything:

```python
board = host(gdb_port=1234)
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf")
board.platform.run(sp.ms(1000))     # waits here until GDB attaches
```

In another terminal, with the GDB from the Zephyr SDK:

```sh
riscv64-zephyr-elf-gdb build/zephyr/zephyr.elf
(gdb) target remote :1234
(gdb) break main
(gdb) continue
```

⚠️ Start the run first and attach second, as here. The port is open as soon as the platform is built, and a debugger that attaches before `run` is shown registers from before the CPU's reset, a program counter of 0 among them ([upstream.md](upstream.md)).

Breakpoints, stepping, backtraces and reading memory all work as on hardware. Simulated time only moves while the CPU runs, so you can sit at a breakpoint for as long as you like and no timer will have fired when you come back.

⚠️ One CPU per simulation can have a GDB port. On the host with the SSD, choose which: `host(gdb_port=1234, drive_blocks=4096, drive=add_ssd)` debugs the host's firmware, and `drive=functools.partial(add_ssd, gdb_port=1234)` the SSD's. While the CPU you are debugging sits at a breakpoint the whole simulation waits, so the other CPU is not running either and will not have given up on you when you continue. 🚧 A debugger on each CPU at once is planned ([plan.md](plan.md), M8).

## When it does not boot

- **`load_elf` refuses the image.** It says why: the image was built for another word size, or it does not start at the CPU's reset vector. The second usually means it was built for a different board.
- **Nothing is printed.** The firmware has most likely faulted before its console was up. Check that the image was built for `socpuppet_host`. A build for another board will touch devices that are not there. So will a build with the drive's shield on a host described with no drive.
- **"Nothing took an access at address ..."** in the log. The firmware reached for a device the board does not have. The address says which.

## Changing the board

The board is a Python description: `python/socpuppet/boards/host.py`. To try a different memory map or another device, copy it, change it, and print its devicetree with `socpuppet devicetree my_board.py`. For Zephyr to build against it you also need a board directory of your own. Copy `socpuppet_host`'s from the module and replace its `.dts` with what you printed. If your platform has more than one CPU, say whose devicetree you want: `socpuppet devicetree my_board.py --via compute.cpu.socket`.
