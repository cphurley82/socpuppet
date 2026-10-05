# Boot your firmware here 🧦

How to run a Zephyr application on socpuppet's host board. You need Python 3.12 or newer and a Zephyr workspace with the Zephyr SDK. socpuppet is tested with Zephyr 4.4.2 and SDK 1.0.1.

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
- **Nothing is printed.** The firmware has most likely faulted before its console was up. Check that the image was built for `socpuppet_host`. A build for another board will touch devices that are not there.
- **"Nothing took an access at address ..."** in the log. The firmware reached for a device the board does not have. The address says which.

## Changing the board

The board is a Python description: `python/socpuppet/boards/host.py`. To try a different memory map or another device, copy it, change it, and print its devicetree with `socpuppet devicetree my_board.py`. For Zephyr to build against it you also need a board directory of your own. Copy `socpuppet_host`'s from the module and replace its `.dts` with what you printed.
