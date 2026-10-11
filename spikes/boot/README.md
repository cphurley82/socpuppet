# The boot spike 🚧

Milestone M14 starts with an experiment: four questions about the pieces it borrows, asked before any of its steps is written. The report is [docs/boot-spike.md](../../docs/boot-spike.md).

⚠️ Nothing here is part of socpuppet. It is exploratory code:

- The everyday build, coverage and the wheel never see it. The C++ rig is built only by the `spike` preset.
- Nothing under `src/`, `python/` or `tests/` may include or import it.
- It is not written test-first.
- It goes when M14's steps have put what it found into socpuppet.

## What is here

| Path | Question | Run it |
|---|---|---|
| `flash_rig_test.cpp` | 1. Is the borrowed flash filled by a debug write through its window? | `uv run cmake --preset spike && uv run cmake --build --preset spike --target spike_boot_flash_rig && build/dev/spikes/boot/spike_boot_flash_rig` |
| `rom/` | 2. Does the Zephyr SDK's gcc build a bare-metal ROM for RV32 and RV64? | `spikes/boot/rom/build.sh` |
| `rom_boots.py` | 2, a step further: that ROM boots the host from a memory standing in for the flash | `PYTHONPATH=python uv run python spikes/boot/rom_boots.py` |
| `bin_in_ram.py` | 3. Does Zephyr start from a flat copy of its image? | `PYTHONPATH=python uv run python spikes/boot/bin_in_ram.py` |
| `flatten.py` | 3, the other half: are an ELF's segments, flattened, the `.bin`? | `PYTHONPATH=python uv run python spikes/boot/flatten.py` |
| `zephyr/` | 4. Does Zephyr build for a host with two APLICs, a watchdog and a system controller? | `spikes/boot/zephyr/build.sh` |
| `two_aplics.py` | 4, a step further: the shell image answers on a host with two APLICs | `PYTHONPATH=python uv run python spikes/boot/two_aplics.py` |

The scripts want the firmware built first (`firmware/build.sh`), for its toolchain, its Zephyr and its images. `uv run cmake --preset dev` puts the build tree back to the everyday one.
