# Why socpuppet exists 🧭

socpuppet is a whole system-on-chip simulated on a laptop, with Python pulling the strings, built from open tools only. This page says what it is for, who it is for, and the rules that decide what gets built next. [roadmap.md](roadmap.md) has the milestones; this is the compass they are read by.

## The idea

A system-on-chip (SoC) is a chip with a whole computer on it: processors, memory, the blocks that talk to the outside world, and the wiring between them. A virtual platform (VP) is a simulation of one, good enough that the chip's firmware runs on it without knowing the difference, so that the software can be written and tested before the silicon exists. Chip companies build them with commercial tools. socpuppet builds one with open ones, in the spirit of Raspberry Pi: real, friendly and free.

Real is what makes it good to learn on. The firmware is the real firmware (Zephyr, OpenSBI, UEFI, and next Linux), the protocols are the real protocols, the CPU is a real instruction-set simulator, and the 🎭 stand-ins are the scaffolding around whichever part you are studying, so that one block can be real while everything around it stays simple. Every page explains as it goes, because a chip is learned one block at a time, and the people building this learned each block as they built it.

## Who it is for

A ladder of four. Each rung is written for the person standing on it. The top three stand today; the bottom one is where the project wants to reach.

1. 🌱 **Someone who knows a little Python**, or is learning it, and has never seen a chip from the inside: a first-year engineering student, a high-school student who builds things with an AI's help. They should be able to run a show, change one line and watch the chip do something different, in an afternoon, without knowing what TLM is. 🚧 Not served yet. The release gate below says what it takes.
2. 🎓 **The learner building a first virtual platform**, or curious how a chip boots before the chip exists. The primary reader this year.
3. 🧵 **The firmware developer**, who installs a board with pip, boots their image on it, runs their tests in CI and attaches a debugger.
4. **The engineer who builds virtual platforms for a living**, and wants methodology to take home.

The bottom rung asks three things of every page, and they are rules now rather than promises. A term is defined where it first appears, on the page and not only in [architecture.md](architecture.md)'s glossary. Every example runs as pasted. And the docs work when read beside an AI assistant, which is how that reader will read them, so names are exact and consistent and a page says what it is for in its first line. 💡 The repo already writes instructions for an AI, in `AGENTS.md`. The docs a learner's assistant will read deserve the same care.

## The aims

Numbered, so that a decision can cite one.

1. 🎓 **Teach.** How a SoC boots, and how a virtual platform is built. Every model's page says which real hardware it stands for and what it leaves out.
2. 🧦 **Prove the open flow.** A complete VP methodology from open parts, judged by its workflow and not by its feature count: compose a platform in Python, review a board in git, generate the devicetree and the address map from one description, keep tests behind every model, deliver it with `pip install`, run it in CI. Commercial tools still do some things better, and this page says so: they come with libraries of vendor models, they are faster, and someone answers the phone. socpuppet does not compete with Virtualizer on its model library or its GUI. It competes on the workflow. The vocabulary stays the industry's (TLM, ISS, DMI), so that someone arriving from a commercial tool feels at home and someone leaving for one is not lost.
3. 🔧 **Be usable at work.** The bar is concrete: a firmware team installs the wheel, boots its image, runs its tests in CI and attaches gdb, with no licence server anywhere. The time it takes a newcomer to reach a first boot is a release criterion, and it is measured.
4. 📮 **Borrow, and give back.** An open project that fits is used before anything is written, behind an adapter of ours and a contract suite that says what we rely on. A fix to someone else's code is a patch in `cmake/patches/` with an entry in [upstream.md](upstream.md), and the patches go upstream on the release track below.
5. 💡 **Be a place to try ideas.** The experiments that matter most are in method, not in the number of devices: how a board is described, how a borrowed model is held to a contract, how a platform is delivered. The list at the end of this page is for anyone who wants to take a practice home to their own project.
6. 🐧 **Run real workloads.** Linux is the customer that asks for the rest of a server SoC: more than one hart, an IOMMU, PCIe enumeration, the interrupt fabric, a boot chain with firmware at every stage. An AI workload on Linux is the long-term goal.

## Other uses

None of these is a commitment. Each is something the platform is already shaped for.

- **Debugging.** Every CPU in one SystemC kernel means one clock and one step for all of them, a debugger on each, and a trace of everything that crossed a socket. A second hart, QEMU's by way of QBox, is there to tell a bug of the hart's from one of the firmware's.
- **Structural exploration.** Where the DRAM lives, whether the AI processor gets a die of its own, one socket or two. Cheap, because a platform is a Python function and a variant is another one. Performance exploration waits for a timed tier with a question behind it.
- **Understanding a binary you did not write.** Run it, and read what it touched: 🎭 stand-ins answer anything and record what was asked. Booting a stock kernel is exactly this exercise.
- **Modelling a real chip** from public documents alone, a game console say, as a board of its own. A maybe. Nothing from under an NDA, ever.

## How choices get made

The rules that order the milestones and settle a decision. When two pull against each other, the earlier one wins.

- **Clarity and correctness first**, before speed, and before charm.
- **Real over toy.** A stock kernel and unpatched firmware wherever possible; a patch to borrowed firmware is a finding to report, not a convenience.
- **Linux asks, we build.** After the first Linux prompt, the order is what the kernel needs next and what teaches most.
- **What a block does matters; how long it takes is a tier.** Timing is added to one block at a time, as an optional tier, when a question needs it, and never to the platform at large.
- **Borrow before building**, and fix upstream's copy before writing our own.
- **Every block arrives the same way**: a slot and its contract suite, a borrowed model where one fits, a register map in `regs/`, a 🎭 stand-in before the full model and both kept, a driver in the Zephyr module, a page under `docs/models/`.
- **A newcomer builds it for free on a laptop.** No tool, licence or machine a student cannot have.

## Not now

Things socpuppet is not trying to be, so that nobody waits for them: cycle accuracy; PHY and electrical detail; a GUI; a performance model to rival gem5; anything proprietary or from under an NDA; and any claim of compliance, with UCIe, PCIe or NVMe. Each can be revisited with a reason. None is on the plan.

## The release gate

socpuppet is not on PyPI yet. These are the conditions for the first release, drafted to be edited and not yet met:

- Linux boots to a prompt from the wheel, in CI, on both harts.
- The README's first show works from `pip install socpuppet`, on Linux and macOS.
- [boot-your-firmware.md](boot-your-firmware.md) takes a newcomer from nothing to a boot in an afternoon, measured on a real newcomer.
- A front door to the docs that a stranger can find their way through.
- 🌱 A first rung for the Python beginner: one page and one example that need nothing but Python, where the reader changes a line and the chip visibly does something different, measured the same way.

After the gate: the release, a post per act for anyone who wants the story, and the upstream track opens, with the smallest and clearest patches first.

## What socpuppet does differently

The practices worth taking home, kept current as they change:

- **Describe once, generate everything.** A board is a Python function; the devicetree, the address map and the register headers are generated from it, and lint fails when a generated copy drifts.
- **A stand-in is the first driver** of every block, and it stays after the real thing arrives.
- **One contract suite for each slot**, which a stand-in and the full model both pass before either is used in a boot.
- **A ledger for borrowed code**: every patch a file, every limitation an entry, and nothing sent until it is ready.
- **Tests before models**, and a milestone's exit is an automated test in CI.
- **A platform is a wheel.** The firmware developer gets it with pip, like any other library.
- **Every firmware in one kernel**, so that three CPUs step together and a debugger sits on each.
- **A second hart as a second opinion.** Two CPUs written by different people rarely share a mistake.
