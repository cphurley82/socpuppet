# The labs 🧪

A lab is a session at the keyboard: a short page of commands to run, in order, with a line under each saying what to look at, and a link for the why. Where the other docs explain, a lab has you do; read one beside a terminal, not instead of one.

| Lab | What you do |
|---|---|
| [Linux, end to end](linux-tour.md) | 🐧 Boot a stock Linux kernel on the whole cast, type at its shell and `ssh` into it, swap the CPU for QEMU's, swap 🎭 stand-ins (simplified models that hold a block's place) for the real models and watch what changes, and poke at the logs, the traces and a debugger |

## How a lab is kept

- **Every command runs as pasted**, from the top of a checkout, and was run before the lab landed. A number on a page is a measurement from that run, and says what machine it was.
- 🧵 **A step that needs Python is a file in [`examples/`](../../examples/)**, run by `ctest` like the other examples, so that it keeps working. The ones that boot Linux at the console carry the label `qbox` and run on QBox's hart (a *hart* is RISC-V's word for one CPU core as software sees it; QBox wraps QEMU's as a SystemC model), where a boot takes seconds: `ctest --preset dev` leaves them out, and `ctest --preset qbox` runs them, every night; the one with a 🔌 cable to this machine's network carries `nightly` and runs on the interpreter (the project's own CPU model, which executes instructions one by one) in the nightly `ctest --preset dev`, since ssh to QBox's hart under the pump (the loop that keeps the simulated clock to the wall's) is a loose end ([development.md](../development.md)).
- **A lab links out for the why.** The mechanism lives on the page that owns it: a board on [boards.md](../boards.md), a block on its page under [models/](../models/), Linux on [linux.md](../linux.md).

🧦 The labs sit between the [README](../../README.md), which runs a show in a dozen lines, and the pages written for each reader in [the docs' map](../README.md).
