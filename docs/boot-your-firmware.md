# Boot your firmware here 🧦

How to run a Zephyr application on socpuppet's host board, from a fresh checkout to Zephyr's hello world, then an application of your own, typing on its console, and a debugger on it. The other boards and the bigger shows, with two or three firmwares at once, are on [boards.md](boards.md); the steps there are these, and each section says what differs.

🚧 socpuppet is not on PyPI yet, so "install" means building it from a checkout: [setup.md](setup.md) takes a bare machine to a built one in three commands, and [development.md](development.md) is the everyday page. Every command below is run from the checkout.

## The board

The board is called `socpuppet_host`. It is a 64-bit RISC-V machine:

| What | Where | Zephyr driver |
|---|---|---|
| CPU | RV64GC, with machine, supervisor and user mode. Starts at `0x8000_0000`, in machine mode, which is where Zephyr stays. ⚠️ No PMP | |
| RAM | `0x8000_0000`, 64 MB | |
| Interrupt controller ([IMSIC](models/imsic.md)) | `0x2400_0000` for machine mode's messages, `0x2800_0000` for the supervisor's. 63 identities | `riscv,imsic`, Zephyr's own, and socpuppet's module for `irq_enable` |
| UART, the console | `0x1000_0000`. Its interrupt line is source 16 of the APLIC | `ns16550` |
| Interrupt controller for wired devices ([APLIC](models/aplic.md)) | `0x100C_0000`. 31 sources, each sent on to the IMSIC as a message | `riscv,aplic`, Zephyr's own, and socpuppet's module for `irq_enable` |
| Machine timer | `0x0200_0000`, 10 MHz | `riscv,machine-timer` |

💡 You do not have to copy this table anywhere. The board's **devicetree**, the description of the hardware that Zephyr is built against, is generated from the same Python description that builds the simulation, so the two cannot disagree about where the UART is. `socpuppet address-map python/socpuppet/boards/host.py` prints the map straight from that description, and [address-map.md](address-map.md) has every board's.

## 1. Build the firmware

The quick way builds every image the tests boot, Zephyr's hello world for this board among them, and fetches what builds them (the Zephyr SDK, Zephyr itself, a west workspace around it) into `build/firmware`. It takes a few minutes the first time:

```sh
uv run firmware/build.py zephyr
```

The image is `build/firmware/hello_world_socpuppet_host.elf`. To build an application of your own, or Zephyr's samples one at a time, use that workspace: it has `west`, Zephyr's build tool, in its own Python environment, and the board lives in a Zephyr module inside the socpuppet package, which one command locates.

```sh
cd build/firmware                                    # the west workspace firmware/build.py made
tools="$PWD/linux-x86_64"                            # this machine's tools: macos-aarch64 on an Apple silicon Mac
export PATH="$tools/venv/bin:$PATH"                  # west, cmake and ninja
export ZEPHYR_SDK_INSTALL_DIR="$tools/zephyr-sdk-1.0.1" ZEPHYR_TOOLCHAIN_VARIANT=zephyr
west build -b socpuppet_host zephyr/samples/hello_world -- \
    -DZEPHYR_EXTRA_MODULES="$(PYTHONPATH=../../python uv run --project ../.. python -m socpuppet zephyr-module)"
```

The image is `build/firmware/build/zephyr/zephyr.elf`. 💡 If you already have a Zephyr workspace of your own with the SDK installed (socpuppet is tested with Zephyr 4.4.2 and SDK 1.0.1), the same `west build` line works from there; `socpuppet zephyr-module` prints the module's path wherever socpuppet is installed.

## 2. Run

```python
import socpuppet as sp
from socpuppet.boards.host import host

board = host()                                      # 🧵 describe the platform
board.platform.build()                              # create the simulation
board.platform.load_elf("build/firmware/hello_world_socpuppet_host.elf")

board.platform.run(sp.ms(100))                      # 100 ms of simulated time
print(board.uart.output)
```

```text
*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_host/socpuppet_rv64
```

Run it with `PYTHONPATH=python uv run python my_show.py` from the checkout. `examples/host_hello.py` is this show with a timeout instead of a fixed duration, and `python -m socpuppet.boards.host <image>` does the same from the command line.

## Typing on the console

🧵 Whoever holds the UART is the other end of its serial line. `uart.output` is the screen, and `uart.write` is the keyboard:

```sh
west build -b socpuppet_host samples/subsys/shell/shell_module -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

```python
board = host()
board.platform.build()
board.platform.load_elf("build/zephyr/zephyr.elf")

board.platform.run_until(lambda: "uart:~$ " in board.uart.output, timeout=sp.ms(200))
board.uart.write("kernel version\n")
board.platform.run_until(lambda: "Zephyr version" in board.uart.output, timeout=sp.ms(200))
board.platform.run(sp.ms(1))        # let the line finish
print(board.uart.output)
```

```text
uart:~$ kernel version
Zephyr version 4.4.2
```

`examples/shell_from_python.py` is that with a few more commands, and it counts the console's interrupts at the end.

- 🧵 **Type before a run or between two.** What is typed waits in the UART until the firmware reads it, and arrives all at once: there is no baud rate. ⚠️ The UART loses none of it, but firmware may. Zephyr's shell reads into a buffer of 64 bytes and drops what does not fit, so type a line at a time.
- 💡 **The shell is woken by the console's interrupt**, and Zephyr works that out for itself: the UART's node in the board's devicetree has an interrupt, so the shell asks to be interrupted and does not poll. With a UART that could not interrupt it would poll, and answer all the same.
- 🎓 **The interrupt is a wire for an inch and a message from there.** The UART is on the IO die and the CPU on the compute die, and the link between them has nowhere for a wire to go. So the UART's line stops at the [APLIC](models/aplic.md) beside it, which writes the interrupt's identity across the link to the CPU's [IMSIC](models/imsic.md). Every interrupt on this board but the timer's arrives that way.
- 💡 **`irq_enable` is all a driver calls.** Zephyr knows an interrupt by one number, and on this board a number from 16 to 31 is a source of the APLIC. socpuppet's module sets the source up when a driver enables it. Wire a device of your own to a free source in the platform description, and its node in the devicetree has the number.

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

In pytest, mark each test that builds a platform with `@pytest.mark.platform`. A process can hold only one simulation, and the marker gives the test a process of its own. `tests/python/test_zephyr_on_the_host_board.py` is a complete example.

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

💡 On an Intel Mac the Zephyr SDK has no GDB, and `firmware/build.py` has left Linux's in the Docker volume it builds with. Run that one in the image the firmware was built in, which `tools/devcontainer.py` does with the volume in its place. From in there the Mac is called `host.docker.internal`:

```sh
tools/devcontainer.py \
  build/firmware/linux-x86_64/zephyr-sdk-1.0.1/gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-gdb \
  build/firmware/hello_world_socpuppet_host.elf
(gdb) target remote host.docker.internal:1234
```

⚠️ Leave with `continue`, not `detach` or `quit`. A debugger that detaches leaves its CPU stopped, and quitting GDB at a breakpoint detaches. A stopped CPU stops the whole simulation, with no limit in simulated time able to end the run. So say `continue` and let the run finish, which hangs up on GDB, or stop the simulation yourself. If it is too late for that, attach to the same port again and say `continue`.

⚠️ Start the run first and attach second, as here. With the DBT-RISE CPU the port is open as soon as the platform is built, and a debugger that attaches before `run` is shown registers from before the CPU's reset, a program counter of 0 among them ([upstream.md](upstream.md)); with QBox's CPU (`--cpu qbox_cpu`) the port opens when the run starts, and a debugger that attaches before is refused.

Breakpoints, stepping, backtraces and reading memory all work as on hardware. Simulated time only moves while the CPU runs, so you can sit at a breakpoint for as long as you like and no timer will have fired when you come back.

On a board with more than one CPU, give the port to the one whose firmware you are debugging: `host(gdb_port=1234, drive_blocks=4096, drive=add_ssd)` debugs the host's, and `drive=functools.partial(add_ssd, gdb_port=1234)` the SSD's. The other CPU runs without waiting for anybody, and while yours sits at a breakpoint it waits too, so it will not have given up on you when you continue.

## When it does not boot

- **`load_elf` refuses the image.** It says why: the image was built for another word size, or it does not start at the CPU's reset vector. The second usually means it was built for a different board.
- **Nothing is printed.** The firmware has most likely faulted before its console was up. Check that the image was built for `socpuppet_host`. A build for another board will touch devices that are not there. So will a build with the drive's shield on a host described with no drive.
- **"Nothing took an access at address ..."** in the log. The firmware reached for a device the board does not have. The address says which.

## Changing the board

The board is a Python description: `python/socpuppet/boards/host.py`. To try a different memory map or another device, copy it, change it, and print its devicetree with `socpuppet devicetree my_board.py`. For Zephyr to build against it you also need a board directory of your own. Copy `socpuppet_host`'s from the module and replace its `.dts` with what you printed. If your platform has more than one CPU, say whose devicetree you want: `socpuppet devicetree my_board.py --via compute.cpu.socket`.

## More shows

The host is one of three boards. [boards.md](boards.md) has the SSD's controller and the IO die's manager, the host with the SSD and across the link, all three firmwares at once, booting from flash, OpenSBI, UEFI, the watchdog, and a debugger on each of three CPUs. [linux.md](linux.md) boots 🐧 Linux and types at its shell. [twister.md](twister.md) runs Zephyr's own tests, and yours, on every board.
