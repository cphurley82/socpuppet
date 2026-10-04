# The ISS spike 🚧

This is milestone M1: an experiment to find out which CPU model should sit in socpuppet's CPU slot. The plan is in [docs/plan.md](../../docs/plan.md).

🎓 An ISS (instruction-set simulator) is the model that executes the firmware's instructions one after another, the way the real processor would. socpuppet has none yet. Several open ones exist, and writing our own is possible too, so before building anything on top of one we try each candidate out against the same checklist.

⚠️ Nothing here is part of socpuppet. It is exploratory code, written to answer a question and then be thrown away:

- It is not built unless you ask for it (`SOCPUPPET_BUILD_SPIKES`, which the `spike` preset turns on).
- Nothing under `src/`, `python/` or `tests/` may include or import it.
- It is not written test-first and does not count towards coverage. It is still linted, and still built with warnings as errors.
- When M3 builds the real CPU kit, this directory goes.

## Running it

```sh
uv run cmake --preset spike
uv run cmake --build --preset spike
uv run ctest --preset spike              # only the tests labelled `spike`
uv run cmake --preset dev                # back to the everyday build
```

The `spike` preset shares `build/dev` with the others, so go back to `dev` when you are done.

## What is here

| Path | What |
|---|---|
| `cpu_slot.h` | A draft of the CPU slot: the shape a candidate must have, and what the spike expects of it. |
| `harness/virt_board.h` | A board for a candidate to run on: router, RAM and a UART at the addresses of QEMU's RISC-V `virt` machine, so a stock Zephyr image runs without a board of our own. |
| `harness/standin_uart.h` | 🎭 A stand-in for the NS16550 UART. It is always ready to transmit and keeps every byte for the test to read. |
| `harness/harness_test.cpp` | The harness on its own, with the scripted bus master playing the CPU. |
