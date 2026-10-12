# The twister spike 🚧

A spike for milestone M21 in [docs/plan.md](../../docs/plan.md): can Zephyr's test runner, **twister**, run Zephyr's own test suites on socpuppet's boards, with socpuppet as the emulator? The report is [docs/twister-spike.md](../../docs/twister-spike.md).

🎓 Twister is the program Zephyr's own CI runs: it finds every `testcase.yaml` and `sample.yaml` under a directory, builds each for each board asked for, runs the result on an emulator or a board, and reads the console for a verdict. **ztest** is Zephyr's test framework, the thing that prints `PASS - [suite.case]` and `PROJECT EXECUTION SUCCESSFUL`, and twister's default way of judging a run.

⚠️ Nothing here is part of socpuppet. It is exploratory code:

- No preset, CI job or wheel builds or runs it.
- Nothing under `src/`, `python/` or `tests/` may include or import it. The twister files it adds to the boards go into a *copy* of the Zephyr module under `build/twister/`, never into `python/socpuppet/zephyr_module/`.
- It is not written test-first and does not count towards coverage.
- It imports socpuppet's Python and boots the ROM `firmware/build.sh` builds, so a change there can break it without anything saying so. Run it again before building on it.

## What is here

| Path | What |
|---|---|
| `twister.sh` | The recipe. Runs twister with socpuppet as the emulator, in the devcontainer's image on an Intel Mac (the Zephyr SDK has no toolchain for one). `--suites` runs every line of `suites.txt`. |
| `run.py`, `bin/socpuppet-run` | What twister invokes to run one image: describes the board, gives the CPU its image (from a ROM and a flash by default, so that a test that resets its CPU survives it), and prints the console a whole line at a time until ztest's verdict. |
| `boards/<board>/board.cmake`, `boards/<board>/<board>.yaml` | The two files a board needs for twister: the `run_custom` target, and the platform file that says the board is simulated by `socpuppet-run`. |
| `overlays/watchdog0_<board>.overlay` | The `watchdog0` alias Zephyr's watchdog test looks for, which the boards' devicetrees do not have. |
| `tests/drivers/syscon_reset_cause/` | Question 5: a ztest suite of our own, beside the drivers, found and run by twister. |
| `suites.txt` | The Zephyr suites the spike ran, with the flags each needs. |

## How to run it

Build the firmware first (`firmware/build.sh`), which leaves the SDK, Zephyr and a venv in `build/firmware`. Then:

```sh
spikes/twister/twister.sh -p socpuppet_host -T tests/kernel/common -v     # one suite
spikes/twister/twister.sh --suites -p socpuppet_host -p socpuppet_ssd      # all of suites.txt
```

A `-T` that is relative is under Zephyr's tree, unless it starts with `spikes/`. The results are in `build/twister/out`: `twister.json`, and a `handler.log` with the console of every run. The first run on an Intel Mac builds socpuppet for Linux inside the container (about ten minutes) and copies Zephyr and the SDK to a Docker volume, `socpuppet-twister` (a minute), because the compiler reading them through Docker's file sharing made every scenario ten times slower; the report's question 7 has the figures. After that a scenario is about four seconds. `docker volume rm socpuppet-twister` throws the copy away.

Two switches exist for the measurements and nothing else: `SOCPUPPET_TWISTER_BIND=1` runs everything on the bind mount, `SOCPUPPET_TWISTER_CCACHE=1` adds ccache.

To run one image by hand, on this machine, without twister:

```sh
PYTHONPATH=python uv run python -u spikes/twister/run.py \
    build/firmware/flash_test_socpuppet_ssd.elf --board socpuppet_ssd
```
