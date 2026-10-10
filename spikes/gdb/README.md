# The GDB spike 🚧

Milestone M8 wants a debugger on each of three CPUs at once, and DBT-RISE had one GDB server for the whole process. This spike asked whether that could be fixed, and what the other CPUs do while one of them sits at a breakpoint. It could, and they wait. The report, with what was measured and what was decided, is [docs/gdb-spike.md](../../docs/gdb-spike.md).

🎓 GDB does not need to be in the same program as the thing it debugs. It talks to a *GDB server* over a TCP connection, in a text protocol called the remote serial protocol (RSP). A CPU model that has such a server can be debugged by any GDB that knows its instruction set.

⚠️ Nothing here is part of socpuppet. It is exploratory code:

- No preset, CI job or wheel runs it.
- Nothing under `src/`, `python/` or `tests/` may include or import it. It imports the tests' `GdbClient`, which is the direction that is allowed.
- It is not written test-first and does not count towards coverage.
- It goes when M8's step 4 lands, which is the step that makes three GDB ports a tested feature. [plan.md](../../docs/plan.md) will name the last commit that holds it.

## What is here

| Path | What |
|---|---|
| `three_debuggers.py` | The experiments. Each builds the host with all three firmwares and a GDB port on every CPU, and speaks RSP to the three servers from three threads. |
| `real_gdb.sh` | The same with the real thing: three of the Zephyr SDK's GDBs at once, each with its firmware's symbols, a breakpoint on `main`, and a backtrace when it is hit. |
| `a-port-each.patch` | The one change to socpuppet's own code that the experiments need: the CPU model stops refusing a second `gdb_port`. It is not applied in the tree. M8's step 4 makes that change test-first. |

The changes to DBT-RISE itself are not here. They are three patches in `cmake/patches/`, applied by the build like every other, and written up in [docs/upstream.md](../../docs/upstream.md).

## Running it

```sh
firmware/build.sh                                  # the three images, into build/firmware
git apply spikes/gdb/a-port-each.patch             # ⚠️ changes src/, take it out again after
uv run cmake --build --preset dev

uv run python spikes/gdb/three_debuggers.py attach
uv run python spikes/gdb/three_debuggers.py frozen
uv run python spikes/gdb/three_debuggers.py breakpoints
uv run python spikes/gdb/three_debuggers.py detach
spikes/gdb/real_gdb.sh                             # on an Intel Mac: spikes/gdb/real_gdb.sh docker

git apply --reverse spikes/gdb/a-port-each.patch
uv run cmake --build --preset dev
```

| Experiment | What it shows |
|---|---|
| `attach` | Each debugger finds its own CPU stopped where its firmware starts, reads that firmware out of memory, and is sent the description of the right kind of core (64-bit for the host, 32-bit for the other two). Each says continue and the boot runs to the disk test's verdict. |
| `frozen` | The first debugger to find its CPU stopped holds it for two seconds. The other two are answered only after it lets go: a stopped CPU stops the world. |
| `breakpoints` | A breakpoint on `main` in each firmware is hit, each once, at 1.4 ms, 3.3 ms and 142.7 ms of simulated time, and the boot goes on. |
| `detach` | A debugger that detaches leaves its CPU stopped, and the simulation with it. A second debugger can attach to the same port and say continue. |
| `serve A B C` | Listens on three ports and runs to the verdict. `real_gdb.sh` uses it. With `0 0 0` there is no debugger at all, which times the three-firmware boot. |

Set `SPIKE_LIVE=1` to see what each debugger does as it does it, and `SPIKE_TRACE=1` to see every packet. ⚠️ A CPU waiting for its debugger holds the simulation's only thread, and no limit in simulated time can end that. So each run gives up after `SPIKE_WALL_LIMIT` seconds of wall clock (180 unless set).
