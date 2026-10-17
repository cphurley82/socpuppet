# The NPU spike 🚧

Milestone M12 is an experiment: what should sit in socpuppet's accelerator slot, the place for an AI processor? Two candidates were tried behind one draft slot, and the report, with the recommendation, is [docs/history/npu-spike.md](../../docs/history/npu-spike.md).

🎓 An NPU (neural processing unit) is the block an SoC hands its matrix arithmetic to. Firmware describes the work in memory, rings a doorbell, and is interrupted when the block is done. The spike's one job is a matrix multiply of 8-bit integers, which is the kernel every neural network spends most of its time in.

⚠️ Nothing here is part of socpuppet. It is exploratory code:

- The everyday build, coverage and the wheel never see it. It is built only by the `spike` preset, which turns on `SOCPUPPET_BUILD_SPIKES`.
- Nothing under `src/`, `python/` or `tests/` may include or import it.
- It is not written test-first and does not count towards coverage.
- It includes socpuppet's platform headers and the tests' support headers, so a change there can break it without anything saying so. Run it again before building on it.

## What is here

| Path | What |
|---|---|
| `accelerator_slot.h` | The draft slot: a bus master, a register block and an interrupt line. |
| `doorbell.h` | The one block of ours that both candidates share. Its register map, the descriptor a job is described by, and the logic with no simulator attached. |
| `doorbell_module.h`, `doorbell_test.cpp` | The doorbell as a block on the bus, with a face for the host and a face for a core of the accelerator's own, and the test that rings it with 🎭 a stand-in core. |
| `behavioral/` | 🎭 The behavioral NPU: the DMA engine's SystemC shell around `NpuLogic`, with the arithmetic behind a `Multiplier`. Two flavours: `PlainMultiplier` is a triple loop in C++, and `NumpyMultiplier` hands the arrays to numpy through socpuppet's `PythonExecutor`. |
| `hexagon/` | QBox's Hexagon DSP behind the slot: a Dockerfile and a build script for QBox with its Hexagon core, the program the core runs (`firmware/`), and the integration that is built in the container (`integration/`). |

## Running it

The behavioral candidate and the doorbell are tests in the main build tree, behind the preset:

```sh
uv sync --group spike                  # numpy, for the numpy flavour
uv run cmake --preset spike
uv run cmake --build --preset spike
uv run ctest --preset spike            # just the spike's tests
```

Each test prints how long the machine took over the spike's 256 by 256 multiply, on a line marked `SPIKE`. ⚠️ The kernel cannot be restarted, so running a test program by hand runs only its first test to a verdict; `ctest` runs each in a process of its own. 💡 The `spike` preset shares `build/dev` with the others; `uv run cmake --preset dev` goes back.

The Hexagon candidate needs QBox, which is GPL-2.0 underneath (it is QEMU) and is never in the wheel, so it is built on its own in a container. The first build takes a while and a few gigabytes, kept in a Docker volume:

```sh
docker build -t socpuppet-qbox-hexagon spikes/npu/hexagon
docker run --rm -v socpuppet-qbox-hexagon:/qbox -v "$PWD:/workspace" \
  socpuppet-qbox-hexagon /workspace/spikes/npu/hexagon/build.sh
docker run --rm -v socpuppet-qbox-hexagon:/qbox -v "$PWD:/workspace" socpuppet-qbox-hexagon sh -c '
  cmake -S /workspace/spikes/npu/hexagon/integration -B /qbox/integration &&
  cmake --build /qbox/integration &&
  ctest --test-dir /qbox/integration --output-on-failure'
```

The Hexagon program is compiled by the container's clang, which has the Hexagon back end in it, with no toolchain of Qualcomm's.
