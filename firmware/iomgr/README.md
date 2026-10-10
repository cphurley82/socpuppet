# The IO-die manager's firmware 🧦

A Zephyr application for the board `socpuppet_iomgr`: what runs on the RISC-V core on the IO die of socpuppet's chiplet host, and brings the chip up.

🎓 A chiplet host is one chip built from several dies. The die-to-die link between them does not work when the power comes on: it has to be trained first, and until it is, nothing crosses it. The compute die's CPU is held in reset meanwhile, because nothing it could reach would answer — and it cannot release itself. So one die has to go first, and that is this one.

Three steps, and three lines on the console:

```text
iomgr: training the D2D link
iomgr: D2D link up
iomgr: compute die released
```

After that it sleeps until the link says it has gone down, and trains it again.

It reaches the link through one driver in socpuppet's Zephyr module (`python/socpuppet/zephyr_module/drivers/d2d/ucie_link.c`): the training through a small API of its own, in `<socpuppet/drivers/ucie_link.h>`, and letting the other die go through Zephyr's reset API, because the other die is the link's one reset line.

💡 `python/socpuppet/io_manager.py` is 🎭 the same firmware as a Python script, step for step. It stands in for this one where there is no CPU on the IO die.

Build it as any Zephyr application for the board, or with `firmware/build.sh`, which builds every image the tests boot:

```sh
firmware/build.sh
```
