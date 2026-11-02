# Your first show 🌱

A chip that answers when you type at it, in a dozen lines of Python, for someone who knows a little Python and has never seen a chip from the inside. You change one line, and the chip says something different. 🚧 Until socpuppet is on PyPI, "install" means a checkout built as the [README](../README.md#try-it) says, in three commands; the one-line install is on its way ([roadmap.md](roadmap.md)).

## The cast

Four words, then the show.

- A **chip** here is a system-on-chip, a whole computer on one piece of silicon: a processor, memory, and the blocks that talk to the outside world. socpuppet simulates one: a program on your laptop that behaves as the chip would, closely enough that the chip's own software cannot tell.
- The **board** is the description of a chip in Python: which blocks, and where. This show uses the host, `socpuppet_host`, a 64-bit RISC-V machine with one processor, some RAM and a serial port.
- **Firmware** is the program a chip runs. Here it is [Zephyr](https://zephyrproject.org), a small operating system for small computers, built with its **shell**: a program that reads a typed command and answers it, as the terminal on your laptop does.
- The **console** is the chip's keyboard and screen, which is one serial port: a **UART**, the block that sends and receives text a character at a time. 🧵 Python holds the other end of its cable. `board.uart.output` is the screen, and `board.uart.write` is the keyboard.

## The show

Save this as `my_show.py` and run it from the top of your checkout with `PYTHONPATH=python uv run python my_show.py`; it is also in the checkout as `examples/first_show.py`, where the tests run it. The first time, socpuppet fetches the firmware image and keeps it; after that the show takes about a second.

```python
import socpuppet as sp
from socpuppet import images
from socpuppet.boards.host import host

board = host()                                      # 🧵 the chip, described in Python
board.platform.build()                              # make the simulation
board.platform.load_elf(                            # Zephyr's shell, built for this chip
    images.find("shell_module_socpuppet_host.elf")
)

board.platform.run_until(                           # boot, until the shell prompts
    lambda: "uart:~$ " in board.uart.output, timeout=sp.ms(200)
)
board.uart.write("kernel version\n")                # 🧵 type a command. Change this line!
board.platform.run(sp.ms(200))                      # give the chip 200 ms to answer
print(board.uart.output)
```

```text
uart:~$ kernel version
Zephyr version 4.4.2
```

## What just happened

1. `host()` described the chip and `build()` made it: there is now a simulated processor, with its RAM and its UART, waiting with nothing to run.
2. `load_elf` put Zephyr's shell into its memory, as a factory would write firmware into a real chip.
3. `run_until` let the chip run until the shell's prompt, `uart:~$`, appeared on the console. 💡 The time here is the chip's own: it moves only while the chip runs, so those 200 milliseconds of its time took a fraction of a second of yours, and it stopped early, at the prompt.
4. `write` typed a line at the console. The shell read it, as it would from a real keyboard, and answered.
5. `print` showed the screen.

🎓 Nothing in Zephyr knows it is in a simulation. It is the same shell that runs on a real board, built for this one from the board's description; the chip's keyboard just happens to be a Python string.

## Change a line

Change the command and run it again. The chip answers each one differently, and never tires of being asked.

| Type | What comes back |
|---|---|
| `kernel uptime` | How long the chip has been running, by its own clock |
| `device list` | Every hardware block the firmware found, each with its address: three interrupt controllers and the UART. 💡 It takes the shell longer to say than the others, which is why the chip gets 200 ms |
| `help` | Everything the shell knows how to do |

Two more lines to change, once that is old news:

- Give the chip less time: `sp.ms(200)` to `sp.us(50)`, fifty microseconds. Nothing comes back, not even your own typing, because the shell had not got round to reading the line when the chip stopped. Its time is yours to hand out.
- Type twice: a second `board.uart.write(...)` and a second `run` after the first. The screen shows both, in order, as a real terminal would.

## What next

- 🚀 [Boot your firmware here](boot-your-firmware.md): the same show with a firmware you build yourself, and a debugger on it.
- 🧪 [The labs](labs/README.md): sessions at the keyboard, 🐧 Linux included.
- 💡 [How socpuppet is put together](architecture.md): the words the other pages use, such as TLM and the quantum, what a 🎭 stand-in is, and a page for every block.
