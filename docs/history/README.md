# How socpuppet got here 🧦

The story of how the platform was built, for anyone who wants it. What is on stage today is in [architecture.md](../architecture.md), what comes next in [roadmap.md](../roadmap.md), and why in [vision.md](../vision.md); nothing here is needed to use socpuppet. It is kept because a decision is easier to revisit when its reason is written down, and because the mistakes were the expensive part of the lesson.

- [decisions.md](decisions.md): every decision that settled how socpuppet is built, dated, with its reason and where the reasoning lives. Newest first.
- [lessons.md](lessons.md): what building it taught, by topic. The gotchas a contributor wants to know before touching that area.
- [founding-brief.md](founding-brief.md): the brief the project started from on 2026-10-03, kept as it was written.
- The spike reports, below. A **spike** is a short, time-boxed experiment that answers a design question by trying it; its code is thrown away once the answer is rebuilt test-first, and the report names the last commit that held it.

| Spike | For | Run | The question | The answer |
|---|---|---|---|---|
| [iss-spike.md](iss-spike.md) | M1 | 2026-10-03 to 04 | Which CPU model goes in the CPU slot? | DBT-RISE-RISCV, with QBox optional and from source |
| [pcie-spike.md](pcie-spike.md) | M2 | 2026-10-05 | Borrow VCML's PCIe endpoint, or write our own? | Our own; VCML stays out of the build |
| [gdb-spike.md](gdb-spike.md) | M8 | 2026-10-10 | Can each of three CPUs have a debugger at once? | Yes, by three patches; a stopped CPU stops the world, by design |
| [npu-spike.md](npu-spike.md) | M12 | 2026-10-10 | A Hexagon from QBox, or a behavioral NPU of our own? | 🎭 A behavioral NPU of ours, its arithmetic in Python |
| [aia-spike.md](aia-spike.md) | M13 | 2026-10-10 | Does Zephyr build for an IMSIC and no PLIC? | Yes, with glue the module supplies |
| [boot-spike.md](boot-spike.md) | M14 | 2026-10-11 | Four questions before a CPU boots from flash | All four answered; no change of scope |
| [twister-spike.md](twister-spike.md) | M21 | 2026-10-11 | Can Zephyr's test runner run Zephyr's own tests on the puppet? | Yes; it became `socpuppet run` and [twister.md](../twister.md) |
| [speed-spike.md](speed-spike.md) | M26 | 2026-10-13 | Where to do the Linux work, and which CPU ships? | The interpreter ships, unchanged; QBox became the second hart |
| [virtio-spike.md](virtio-spike.md) | M25 | 2026-10-16 to 17 | What does it take to boot Linux on virtio's cast? | The virtio road to Linux first, on the host as it is |
| [real-host-spike.md](real-host-spike.md) | M30 | 2026-10-22 | Can this machine's own Linux mount the puppet's SSD, through pciem? | Yes, all three drives; build M31 as planned, with corrections |

Two spikes still have code in the tree, behind the `spike` CMake preset: `spikes/npu`, which M19 keeps until it has rebuilt what the decision kept, and `spikes/speed`, which stays so that every later change to the core can be timed against its results ([development.md](../development.md#spikes)).
