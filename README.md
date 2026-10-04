# socpuppet 🧦

**SoC Puppet** (say "sock puppet") is an open-source virtual platform: a whole system-on-chip simulated on your laptop, with Python pulling the strings.

> 🚧 Early days. The plan is written and the build is just starting, so nothing here runs yet. The roadmap is in [docs/plan.md](docs/plan.md).

## What's the show?

A chiplet host and an NVMe SSD, each booting its own [Zephyr](https://zephyrproject.org) firmware, inside one SystemC simulation that you compose and drive from Python.

- 🧵 **Python holds the strings.** Compose a platform, load firmware, then run, step, peek, poke and inject faults from a script or a test.
- 🎭 **Every block has a stand-in.** Any CPU, link or device can be swapped for a simpler one that holds its place, so you can study one piece with everything around it simplified.
- 🎓 **Built to teach.** Each model explains the real hardware it represents and what it simplifies.
- 🔧 **Built to use.** Open tools only (SystemC, Zephyr, RISC-V) and tests behind every model, following the way commercial virtual platforms are built.

## Who's it for?

Anyone curious about how a chip boots before the chip exists. In the spirit of Raspberry Pi, socpuppet aims to be friendly enough to learn on and solid enough to do real work with.
