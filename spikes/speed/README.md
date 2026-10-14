# The speed spike ⏱️

Milestone M26 asks how fast the host's core is, and on which machine, in which environment and with which CPU the work to boot Linux is best done. It times the core on three loops, on every CPU that can be built and every machine it can be built on, and times what a developer waits for on each: a build, a rebuild and the test suite. The report, with the recommendation, is [docs/speed-spike.md](../../docs/speed-spike.md).

⚠️ Nothing here is part of socpuppet. It is exploratory code, held to the rules of `spikes/`:

- The everyday build, coverage and the wheel never see it. It is built only with `SOCPUPPET_BUILD_SPIKES`, which the `spike` preset turns on.
- Nothing under `src/`, `python/` or `tests/` may include or import it.
- It is not written test-first and does not count towards coverage.

💡 Unlike M1's harness, this one stays after its milestone. Every later change to the core can be timed against the lines in `results/`, and a new machine adds a file there.

## The three loops

🎓 A loop of two instructions flatters an interpreter, which is what M1's report said of its own figure, so there are two more. All three are made of `tests/cpp/support/riscv_program.h` and nothing else (`loops.h`), and run on the host's core, the one with supervisor mode, with its RAM behind a probe that counts transactions.

| Loop | What it does | What it measures |
|---|---|---|
| `counted` | M1's loop: count down from 2²⁴, two instructions a time round. Paging off. 33.5 million instructions | The best case: the same two instructions over and over |
| `walks` | Supervisor mode under Sv39 loads from 32 pages in turn, and each round ends with `sfence.vma`, so that every load of the next round is a walk of the page tables. 2¹⁷ rounds, 17.6 million instructions, 4.3 million walks | The worst case: a kernel that has just switched address spaces |
| `hits` | The same loop with a `nop` where the `sfence.vma` was, so every translation after the first round is one the hart kept | What paging costs when it costs least |

The counted loop runs twice, at the quantum the Python boards use (100 µs) and at M1's (1 ms). Each test asserts only that its program finished and that it ran by direct memory access, and prints one line of JSON marked `[speed]`. Nothing asserts anything about time.

## Running it

In the main build tree, behind the preset:

```sh
uv run cmake --preset spike
uv run cmake --build --preset spike --target spike_speed_tests
uv run ctest --preset speed            # one at a time, verbose
```

For a result to keep, `run.sh` does the whole of one environment's column in a tree of its own, `build/speed-<label>`: it configures, cleans and times a build from nothing, touches `src/socpuppet/models/dbt_rise_cpu.cpp` and times the rebuild, times the `dev` suite (everything but the spikes, eight at a time), and runs the speed tests three times. Every line goes to `results/<label>.jsonl`:

```sh
spikes/speed/run.sh --env native-macos-x86_64
spikes/speed/docker.sh amd64 --env docker-amd64-on-macpro    # in the devcontainer's image
```

The label is one of seven, so that a line says where it came from, and `run.sh` refuses any other: `native-macos-x86_64` and `docker-amd64-on-macpro` (the Mac Pro), `native-macos-arm64`, `docker-arm64-on-air` and `docker-amd64-rosetta-on-air` (the MacBook Air), and `native-linux-x86_64` and `docker-amd64-on-ubuntu` (the Ubuntu box). `--backends` and `--default-backend` build and choose DBT-RISE's other backends (M26's steps 4 and 5), and the comment at the top of `run.sh` has the rest.

⚠️ Timings are only as quiet as the machine. Run nothing else while a column runs, and keep a laptop on its charger.

⚠️ The extension is built into `python/socpuppet/`, whichever tree built it last. `run.sh` keeps the one that was there and puts it back when it ends.

## What is here

| Path | What |
|---|---|
| `loops.h` | The three programs, and what each costs worked out from its shape: instructions and walks. |
| `speed_test.cpp` | The platform and one test for each loop. |
| `run.sh` | One environment's column: the build, the suite and the speed tests, into `results/`. |
| `docker.sh` | `run.sh` in the devcontainer's image, for the Docker columns. |
| `collect.py` | `results/` into the report's tables. |
| `boot_count.py` | The count of instructions to a Linux shell, on QEMU, for the projection. |
| `results/` | Every line every run printed, one file per column. |
