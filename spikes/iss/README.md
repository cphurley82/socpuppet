# What is left of the ISS spike 🚧

Milestone M1 was an experiment: which CPU model should sit in socpuppet's CPU slot? Five were tried, DBT-RISE-RISCV was chosen, and M3a rebuilt it test-first in the main tree (`src/socpuppet/models/dbt_rise_cpu.h`). The report, with what every candidate did, is [docs/iss-spike.md](../../docs/iss-spike.md).

🎓 An ISS (instruction-set simulator) is the model that executes the firmware's instructions one after another, the way the real processor would.

The other candidates have been deleted. The report names the last commit that held each. What stays is `qbox/`, because [QBox](https://github.com/qualcomm/qbox) is on the to-do list in [docs/plan.md](../../docs/plan.md) as an optional, faster CPU that users build from source, and this is where that work starts.

⚠️ Nothing here is part of socpuppet. It is exploratory code:

- No preset, CI job or wheel builds it. QBox is built on its own, in a container, with the commands below.
- Nothing under `src/`, `python/` or `tests/` may include or import it.
- It is not written test-first and does not count towards coverage.
- It includes socpuppet's platform headers, so a change there can break it without anything saying so. Run it again before building on it.

## What is here

| Path | What |
|---|---|
| `qbox/Dockerfile`, `qbox/build.sh` | The recipe: an Ubuntu image with the packages QBox wants, and the script that builds QBox and its QEMU for RISC-V only. |
| `qbox/zephyr.lua`, `qbox/both.lua`, `qbox/measure.py` | QBox on its own, configured the way it expects (Lua), booting Zephyr, and the script that timed it. |
| `qbox/integration/` | QBox's CPU behind the spike's CPU slot, and the test program that runs the spike's suite on it. A CMake project of its own. |
| `qbox/cpu_slot.h` | The spike's draft of the CPU slot. The real one is `CpuSlot` in `src/socpuppet/platform/slots.h`, which also has a timer interrupt input. |
| `qbox/harness/candidate_suite.h` | The tests every candidate was held to: two word sizes together, a trap, sleep, reset, a Zephyr boot, DMI, speed. The contract suite in `tests/cpp/contracts/bus_master_contract.h` grew out of it. |
| `qbox/harness/virt_board.h` | The board a candidate runs on: router, RAM and 🎭 a stand-in UART at the addresses of QEMU's RISC-V `virt` machine, so a stock Zephyr image runs on it. |
| `qbox/harness/rv_asm.h` | Just enough of an assembler to write the bare-metal test programs by hand. |

## Running it

The firmware comes from the main tree's script, and the rest happens in the container. The first QBox build takes about ten minutes and 2.6 GB, kept in a Docker volume.

```sh
firmware/build.sh                         # the Zephyr images, into build/firmware
docker build -t socpuppet-qbox spikes/iss/qbox
docker run --rm -v socpuppet-qbox:/qbox -v "$PWD:/workspace" \
  -e QBOX_CXX_STANDARD=20 socpuppet-qbox /workspace/spikes/iss/qbox/build.sh
docker run --rm -v socpuppet-qbox:/qbox -v "$PWD:/workspace" socpuppet-qbox sh -c '
  cmake -S /workspace/spikes/iss/qbox/integration -B /qbox/integration &&
  cmake --build /qbox/integration &&
  ctest --test-dir /qbox/integration'
```

💡 `QBOX_CXX_STANDARD=20` matters. QBox builds itself as C++17, socpuppet is C++20, and SystemC only links with code built to the same standard. What else that rebuild needs is in the report.
