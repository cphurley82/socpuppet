# Boot your firmware here 🧦

How to run a Zephyr application on one of socpuppet's boards: the host, or [the SSD's controller](#the-ssds-controller). The steps are the host's, and the SSD's section says what differs. You need Python 3.12 or newer and a Zephyr workspace with the Zephyr SDK. socpuppet is tested with Zephyr 4.4.2 and SDK 1.0.1.

🚧 socpuppet is not on PyPI yet. Until it is, "install" means building it from a checkout: see [development.md](development.md).

## The board

The board is called `socpuppet_host`. It is a 64-bit RISC-V machine:

| What | Where | Zephyr driver |
|---|---|---|
| CPU | RV64IMAC, machine mode, starts at `0x8000_0000` | |
| RAM | `0x8000_0000`, 64 MB | |
| Interrupt controller (PLIC) | `0x0C00_0000`, 31 sources | `sifive,plic-1.0.0` |
| UART, the console | `0x1000_0000` | `ns16550` |
| Machine timer | `0x1001_0000`, 10 MHz | `riscv,machine-timer` |

💡 You do not have to copy this table anywhere. The board's devicetree is generated from the platform description, so Zephyr already knows all of it.

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
| MSI-to-PLIC bridge | `0x0200_0000`, to PLIC sources 1 and 2 | (the root complex's driver uses it) |
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
| [NVMe frontend](models/nvme-frontend.md) | `0x1001_0000`, PLIC source 1 | 🚧 |
| [DMA engine](models/dma-engine.md) | `0x1002_0000`, PLIC source 2 | 🚧 |
| [Flash controller](models/flash-controller.md) | `0x1003_0000`, PLIC source 3 | 🚧 |

🚧 The three devices are in the devicetree, with bindings in socpuppet's module, and have no drivers yet. Zephyr boots and prints. Firmware that makes the board a drive is the next milestone, and until then 🎭 [a script](models/ssd-firmware.md) plays that part.

Build for it by naming the board:

```sh
west build -b socpuppet_ssd samples/hello_world -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

The SSD is never alone: it has a host on its PCIe link. `ssd()` describes both, with 🎭 a script for the host, and `idle_host` is a host that does nothing, for when only the firmware matters.

```python
import socpuppet as sp
from socpuppet.boards.ssd import idle_host, ssd

board = ssd(host=idle_host)
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf", via=board.ssd.cpu.socket)

board.platform.run(sp.ms(100))
print(board.ssd.controller.uart.output)
```

```text
*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_ssd/socpuppet_rv32
```

Or `python -m socpuppet.boards.ssd build/zephyr/zephyr.elf`.

- ⚠️ **Say whose firmware it is.** The platform has two places an image could go, so `load_elf` wants `via=board.ssd.cpu.socket`. The same goes for the devicetree: `socpuppet devicetree python/socpuppet/boards/ssd.py --via ssd.cpu.socket` is the SSD's own CPU's view, and the host is not in it.
- **Everything below applies**: waiting for output, looking inside, and GDB, with `ssd(host=idle_host, gdb_port=1234)` and the same `riscv64-zephyr-elf-gdb`, which debugs 32-bit code too.
- `tests/python/test_m4b_exit.py` is a complete example.

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

Breakpoints, stepping, backtraces and reading memory all work as on hardware. Simulated time only moves while the CPU runs, so you can sit at a breakpoint for as long as you like and no timer will have fired when you come back.

⚠️ One CPU per simulation can have a GDB port.

## When it does not boot

- **`load_elf` refuses the image.** It says why: the image was built for another word size, or it does not start at the CPU's reset vector. The second usually means it was built for a different board.
- **Nothing is printed.** The firmware has most likely faulted before its console was up. Check that the image was built for `socpuppet_host`. A build for another board will touch devices that are not there. So will a build with the drive's shield on a host described with no drive.
- **"Nothing took an access at address ..."** in the log. The firmware reached for a device the board does not have. The address says which.

## Changing the board

The board is a Python description: `python/socpuppet/boards/host.py`. To try a different memory map or another device, copy it, change it, and print its devicetree with `socpuppet devicetree my_board.py`. For Zephyr to build against it you also need a board directory of your own. Copy `socpuppet_host`'s from the module and replace its `.dts` with what you printed. If your platform has more than one CPU, say whose devicetree you want: `socpuppet devicetree my_board.py --via compute.cpu.socket`.
