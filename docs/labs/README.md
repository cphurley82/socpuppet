# The labs 🧪

A lab is a session at the keyboard: a short page of commands to run, in order, with a line under each saying what to look at, and a link for the why. Where the other docs explain, a lab has you do; read one beside a terminal, not instead of one.

| Lab | What you do |
|---|---|
| [Linux, end to end](linux-tour.md) | 🐧 Boot a stock Linux kernel on the whole cast, type at its shell and `ssh` into it, swap the CPU for QEMU's, swap 🎭 stand-ins for the real models and watch what changes, and poke at the logs, the traces and a debugger |

## How a lab is kept

- **Every command runs as pasted**, from the top of a checkout, and was run before the lab landed. A number on a page is a measurement from that run, and says what machine it was.
- 🧵 **A step that needs Python is a file in [`examples/`](../../examples/)**, run by `ctest` like the other examples, so that it keeps working. The ones that boot Linux carry the label `long`: the quick test preset leaves them out, and the nightly run of `ctest --preset dev` runs them ([development.md](../development.md)).
- **A lab links out for the why.** The mechanism lives on the page that owns it: a board on [boards.md](../boards.md), a block on its page under [models/](../models/), Linux on [linux.md](../linux.md).

🧦 The labs sit between the [README](../../README.md), which runs a show in a dozen lines, and the pages written for each reader in [the docs' map](../README.md).
