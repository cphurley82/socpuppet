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

The report, with what each candidate did and what is recommended, is [docs/iss-spike.md](../../docs/iss-spike.md).

| Path | What |
|---|---|
| `cpu_slot.h` | A draft of the CPU slot: the shape a candidate must have, and what the spike expects of it. |
| `harness/candidate_suite.h` | The tests every candidate is held to: two word sizes together, a trap, sleep, reset, a Zephyr boot, DMI, speed. |
| `harness/virt_board.h` | A board for a candidate to run on: router, RAM and a UART at the addresses of QEMU's RISC-V `virt` machine, so a stock Zephyr image runs without a board of our own. |
| `harness/standin_uart.h` | 🎭 A stand-in for the NS16550 UART. It is always ready to transmit and keeps every byte for the test to read. |
| `harness/rv_asm.h` | Just enough of an assembler to write the bare-metal test programs by hand. |
| `firmware/build.sh` | Builds the firmware the candidates boot: Zephyr's `hello_world` for the stock `qemu_riscv64` and `qemu_riscv32` boards. |
| `dbt_rise/`, `riscv_vp/`, `inhouse/` | One candidate each: its wrapper for the slot, and the test program that runs the suite on it. |
| `qbox/` | QBox, which is built on its own in a container: the recipe, a standalone platform, and the integration behind the slot. |
| `vcml_probe/` | VCML's UART model in the harness. |
| `patches/` | The source patches each candidate needed, with the reason for each. |

## The firmware

```sh
spikes/iss/firmware/build.sh             # into build/firmware
```

The first run downloads the Zephyr SDK's RISC-V toolchain (about 225 MB) and Zephyr itself into `build/firmware`, and nothing is installed anywhere else. Later runs take seconds. Besides each image it writes a count of the instructions the image uses, which says how much of the instruction set a CPU model needs before this firmware runs on it.
