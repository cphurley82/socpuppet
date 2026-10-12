# The twister spike: Zephyr's own tests on the puppet

This is the report of a spike for milestone M21 in [plan.md](plan.md), run on 2026-10-11. Its code was in `spikes/twister/`, with a README that said how to run each part. It was deleted when M21's steps had rebuilt what it found test-first, and commit `4de4daa` is the last that holds it. 🦜 What replaced each part: `spikes/twister/run.py` is `socpuppet run`, the boards' two files for twister are in the Zephyr module, `twister.sh` and `suites.txt` are `firmware/twister.sh` and `firmware/twister-suites.txt`, and the suite beside the drivers is the first of six in the module's `tests/drivers`. [twister.md](twister.md) is the page for what there is now.

🎓 **Twister** is the program Zephyr's own CI runs: it finds every `testcase.yaml` and `sample.yaml` under a directory, builds each one for each board asked for, runs the result on an emulator or a real board, and reads the console for a verdict. **ztest** is Zephyr's test framework, the thing that prints `PASS - [suite.case]` and `PROJECT EXECUTION SUCCESSFUL`, and the way twister judges a run unless a test says otherwise. Together they are how Zephyr tests itself on a thousand boards, and the question here is whether a socpuppet board can be one of them.

**The questions.** Until now Zephyr has been socpuppet's firmware and not its examiner: two of Zephyr's own tests have ever run on a socpuppet CPU (`disk_access`, `flash/common`), both wrapped by hand, and the verdict read by matching substrings in pytest. Zephyr's tree holds hundreds of suites that test exactly what socpuppet models: the CPU, the timer, the interrupt controllers, the UART, the watchdog, a reset. So:

1. Does twister see the three boards, build Zephyr's tests for them, run each through socpuppet, and read a verdict?
2. Of a list of Zephyr's suites, which pass on which board, and why does each failure fail: a model bug, a missing feature, or an assumption of the test's?
3. Does Zephyr's watchdog test, which resets the CPU and carries on from memory the reset does not touch, pass only when the CPU boots from its ROM?
4. What does it cost, in wall time and in what a CI job needs?
5. Does a ztest suite of our own, kept beside socpuppet's drivers, get found and run the same way?
6. Does the CPU model have PMP, so that Zephyr's user mode is a Kconfig away or a model away?
7. Added afterwards: how should it be run, in CI and on demand on this machine, so that it costs what it has to and no more?

**The answers.** Yes to 1 and 5, with nothing of Zephyr's patched: twister built and ran fifteen suites on all three boards, 126 scenarios, and 80 of them passed, 2413 test cases of 2581. The 46 that did not are five things, and two of them are bugs in socpuppet that no socpuppet test had found (⚠️ below): a sleeping CPU does not wake to an interrupt line that is already high, and the 32-bit boards wake late by more than a quantum. The watchdog test resets the CPU three times and comes back each time from the ROM, and then fails on a disagreement between Zephyr's test and Zephyr's driver. A scenario cost about a minute the way the spike first ran it, and that turned out to be Docker's file sharing and nothing else: with Zephyr and the SDK on a Docker volume the same scenarios run ten times faster (question 7, added afterwards). PMP is in the model already, and user mode is not on the core.

Not established, and said so where it comes up: why the 32-bit boards are late, which was measured and not explained; and what a GitHub runner will take, which is estimated from the container and not measured there.

## 1. Twister runs socpuppet as it runs QEMU

Twister has a *custom emulator* mode (verified in `scripts/pylib/twister/twisterlib/` of the pinned v4.4.2): the board's platform file names a program, the board's `board.cmake` defines a `run_custom` target that calls it, twister runs `ninja run` in the build directory, reads the process's standard output a line at a time, and when the ztest harness has seen `PROJECT EXECUTION SUCCESSFUL` or `FAILED`, or the suite's time is up, ends the process. That is the whole contract, and socpuppet meets it with two files per board and one script:

- `boards/socpuppet/<board>/<board>.yaml`, the platform file: `type: sim`, `arch: riscv`, `simulation: [{name: custom, exec: socpuppet-run}]`, `toolchain: [zephyr]`, the RAM and flash sizes twister filters on, `supported: [watchdog]`, and a `timeout_multiplier`.
- `boards/socpuppet/<board>/board.cmake`: `set(SUPPORTED_EMU_PLATFORMS custom)` and the `run_custom` target, which calls `socpuppet-run <zephyr.elf> --board <board> [--shield <shield>]`.
- `socpuppet-run`, which in the spike is `spikes/twister/run.py` and in M21 becomes `socpuppet run`: describe the board (`host()`, with `drive_blocks=4096` when the shield `socpuppet_host_drive` is on; `ssd(host=idle_host)`; `io_manager(compute=one_round_trip)`), give the CPU its image, and run in slices of a millisecond, printing each whole console line as it appears, until the verdict or a cap in simulated time.

The spike adds the two files to a *copy* of the Zephyr module under `build/twister/module`, so that nothing in `python/` depends on a script in `spikes/`, and `ZEPHYR_EXTRA_MODULES` points at the copy. Twister reads that variable for board discovery (`scripts/zephyr_module.py`) and CMake reads it for the build, so one variable serves both.

`samples/hello_world` on `socpuppet_host`: built, run, `Hello World! socpuppet_host/socpuppet_rv64` matched by the sample's console harness, 57 s for the run of which under a second was the simulation. ✅

What it took to get there, each a thing M21's recipe has to know:

- ⚠️ **`exec` has to be on twister's own `PATH`**, not only ninja's: twister checks `shutil.which(exec)` before it runs anything, and a board whose emulator it cannot find is silently built and never run.
- ⚠️ **A non-zero exit from the emulator is a failed configuration even when the harness passed**, if the process ended before twister had killed it. A sample never prints ztest's verdict, so the runner reaches its cap first. The runner therefore exits 0 at the cap and says so on standard error; a ztest suite that never gave a verdict fails by its silence either way.
- ⚠️ **The runner's Python must outlive the container.** The Linux venv that `docs/development.md` describes for a second build tree had its interpreter in uv's cache inside a container that was gone. `firmware/build.sh` keeps Zephyr's venv alive with `UV_PYTHON_INSTALL_DIR` under `build/`, and the spike does the same; and since socpuppet has no Python dependencies, Zephyr's own venv (Python 3.13, the version the Linux `.so` is built for) runs the simulator with `PYTHONPATH=python`.
- ⚠️ **A build tree whose Python is gone has to go too.** Configuring `build/linux` again without its cache made FetchContent apply the dependency patches a second time, which fails. A clean `build/linux` took ten minutes on this Intel Mac through Docker.
- Twister wants `psutil`, `tabulate`, `natsort`, `anytree`, `junitparser`, `colorama`, `ply`, `pyserial`, `pytest`, `packaging` and `python-dotenv` on top of `requirements-base.txt`: a tenth of `requirements-build-test.txt` and `requirements-run-test.txt`, which pull in gcovr, mypy, opencv and pyocd.
- Twister names the platform `socpuppet_host/socpuppet_rv64`, board and SoC, and passes `BOARD=socpuppet_host` to CMake, which is what `board.cmake` gives the runner.
- The boot ROM names the image after its file, so every run begins `rom: zephyr: N bytes to 0x80000000, jumping to 0x80000000`. The ztest harness ignores it, and the two samples and `tests/arch/riscv/fatal`, which are judged by regular expressions on the console, passed with it there. A suite that insisted on its own first line being the console's first would not.

## 2. Which of Zephyr's suites pass

`spikes/twister/twister.sh --suites -p <board>` ran each line of `suites.txt`. A cell is scenarios passed of scenarios run; a suite has one scenario for each configuration its `testcase.yaml` lists. The three boards do not run the same number, because twister runs a scenario marked `platform_key: arch` on one board of each architecture, and filters some by what a board has.

| Suite | `socpuppet_host` | `socpuppet_ssd` | `socpuppet_iomgr` | Why the failures |
|---|---|---|---|---|
| `tests/kernel/common` | ❌ 0/9 | ✅ 2/2 | ✅ 9/9 | A |
| `tests/kernel/timer/timer_api` | ✅ 1/1 | ❌ 0/1 | ❌ 0/1 | B |
| `tests/kernel/sched/schedule_api` | 5/7 | 3/7 | 3/7 | A on the host, B on the others |
| `tests/kernel/threads/thread_apis` | ✅ 1/1 | ✅ 1/1 | ✅ 1/1 | |
| `tests/kernel/workq/work` | ✅ 1/1 | ❌ 0/1 | ✅ 1/1 | B |
| `tests/kernel/sleep` | ✅ 2/2 | ❌ 0/2 | ❌ 0/2 | B |
| `tests/kernel/context` | ✅ 2/2 | 1/2 | ❌ 0/2 | B |
| `tests/kernel/fatal/exception` | ✅ 1/1 | ✅ 1/1 | ✅ 1/1 | |
| `tests/arch/riscv/fatal` (`-K`) | ✅ 4/4 | ❌ 0/4 | ❌ 0/4 | D |
| `tests/drivers/watchdog/wdt_basic_api` | ❌ 0/1 | ❌ 0/1 | ❌ 0/1 | C |
| `tests/subsys/shell/shell` | ✅ 2/2 | ✅ 2/2 | ✅ 2/2 | |
| `tests/lib/c_lib` | 9/11 | 7/9 | 9/11 | E |
| `samples/hello_world` (`-K`) | ✅ 1/1 | ✅ 1/1 | ✅ 1/1 | |
| `samples/synchronization` (`-K`) | ✅ 1/1 | ✅ 1/1 | ✅ 1/1 | |
| `syscon_reset_cause` (ours, question 5) | ✅ 1/1 | ✅ 1/1 | ✅ 1/1 | |
| **Scenarios** | **31/45** | **20/36** | **29/45** | |

In test cases: 954 of 1022 on the host and 1459 of 1559 on the two 32-bit boards together. A scenario that stops half way counts every case it had run.

### A. ⚠️ A sleeping CPU does not wake to a line that is already high (a bug of ours, in the CPU's path)

All nine scenarios of `kernel.common` on the host stop in `test_timeout_order`, and two of the scheduler's stop in `test_priority_preemptible_wait_prio`, with no verdict and the simulation out of work. Run by hand, `kernel.common` ends at 1287.0 ms of simulated time with nothing scheduled, and the machine timer reads `mtime` = 12870000 and `mtimecmp` = 12864000: the compare value is behind the count, so the timer's line is high, and the CPU is asleep.

How it gets there, from the sources: Zephyr's `riscv_machine_timer` driver writes the compare value it computed (`sys_clock_set_timeout`), which can already be in the past. The borrowed CLINT raises its line at once for such a write (`clint::update_mtime`: `write_mtime_irq(r_mtimecmp <= r_mtime)`), which is right. DBT-RISE's `core_complex` tells the core about an interrupt line only when the line changes (`clint_irq_cb` acts on `clint_irq_i[i].event()`). A core that executes `wfi` after the change has nothing left to wake it, and no event is ever scheduled.

The check: with the simulation stopped there, a debug write of a compare value one millisecond ahead (the line falls, then rises at the new time) woke the CPU, `test_timeout_order` passed and the suite ran on. The same poke on the scheduler's image ran it to `PROJECT EXECUTION SUCCESSFUL`. So the firmware and the timer are right and the wake is what is missing.

💡 [plan.md](plan.md) has had the neighbour of this since M3: "A CPU going to sleep does not let the clock catch up first." This one is not about time. It is a level-sensitive line treated as an edge at the moment of sleeping. The same tests pass on the 32-bit boards, where the timing happens not to line up.

⚠️ **Added when M21's step 1 fixed it: the rise is heard, and what loses it is a write.** The core does set the timer's pending bit when the line rises. Zephyr's interrupt entry then clears that bit in `mip`, which a real hart ignores because the bit is read-only, and DBT-RISE's harts did not. With the compare value already in the past the line never falls, so there is no change to set the bit again. The check above, a compare value poked a millisecond ahead, woke the CPU for that reason: it made the line fall and rise. The fix is in the hart's `mip` and not in how it sleeps, and it is the 32-bit boards' hart too, which got away with it for a reason [plan.md](plan.md) gives under what M21's steps found.

### B. ⚠️ The 32-bit boards wake late, by more than a quantum (ours; measured, not explained)

On `socpuppet_ssd` and `socpuppet_iomgr`, and not on the host, the tests that measure a wait fail by a little: `timer_api.test_sleep_abs` "expected wakeup at 87, got 91", `context.test_cpu_idle` "idled for 113 ticks, expected 100", `sleep.test_usleep` over its upper bound, `work.test_1cpu_system_reschedule` over its maximum, and the time-slicing scenarios "timeslice too big, expected 2010000 got 2011149". A tick is 100 µs on all three boards (`CONFIG_SYS_CLOCK_TICKS_PER_SEC=10000`, tickless), which is also the default quantum.

What was measured: `kernel.context` on `socpuppet_iomgr`, run by hand at three quanta. At 100 µs `test_cpu_idle` is 13 ticks late. At 10 µs and at 1 µs it passes.

| Quantum | `context_cpu_idle` | `context_one_cpu` |
|---|---|---|
| 100 µs (the default) | fails: 113 ticks for 100 | fails: `thread_sleep` timestamp out of range |
| 10 µs | passes | no verdict within 4 s of simulated time |
| 1 µs | passes | no verdict within 4 s of simulated time |

So the quantum is in it. What is not explained: 13 ticks is 1.3 ms, thirteen quanta, where the plan's rule is that a CPU sees an interrupt up to one quantum late; and the host, with the same timer, the same quantum and the same tick, passes every one of these. One difference between the two is known and was not tested: a 32-bit CPU writes `mtimecmp` in three bus accesses (the high half to all ones, the low half, the high half) and reads `mtime` in two or more, where the 64-bit CPU does each in one. That is a suspect and nothing more. The runs with no verdict at the smaller quanta were not looked into either, and may be A.

✅ **Added when M21's step 2 fixed it: the suspect did it, and the host is not innocent.** The borrowed timer takes a write of `mtimecmp` from a CPU that is ahead of the clock by waiting until the clock has caught up, and then reported the same time again as the write's own latency. So each write cost the CPU as much time as it was ahead by, up to a quantum, and a 32-bit CPU makes three. Measured: 59.1 µs lost in one setting of the compare value on a 32-bit CPU that was 19.7 µs ahead, and 19.7 µs on a 64-bit one. The host loses up to a tick each time and the 32-bit boards up to three, and by their verdicts Zephyr's tests allow the one and not the other. A smaller quantum makes the loss smaller, which is all the table above shows. One line in the timer mends it, and every scenario listed here passes on both boards. [plan.md](plan.md) has the measurements under what M21's steps found.

### C. Zephyr's watchdog test and Zephyr's SiFive driver disagree (theirs)

See question 3. The model does what the driver asks of it.

### D. `tests/arch/riscv/fatal` on a 32-bit board (the test's assumption)

The suite is `platform_allow: qemu_riscv64` and its scenarios are named `arch.riscv64.fatal.*`: it matches a dump of 64-bit registers line by line. `-K` forced it onto the 32-bit boards, where the kernel panics as asked and prints the dump with eight digits a register, which no regex of the suite's matches. On the host all four pass, register for register. It is run on the host only.

### E. Two libc scenarios want FatFs (the build's)

`libraries.libc.common.stdio.*` include `ff.h`, from Zephyr's FatFs module. `firmware/build.sh` fetches Zephyr alone, "nothing built here needs any of Zephyr's external modules". They are left out, or the module is fetched when something else wants it.

## 3. The watchdog test comes back from every reset, from the ROM

`tests/drivers/watchdog/wdt_basic_api` keeps its place in memory a reset does not touch (`.noinit`), lets the watchdog reset the CPU, and looks at what it left there when it starts again. Its `testcase.yaml` says `expect_reboot: true`, so twister takes several starts of one suite in its stride. It filters on a devicetree alias, `watchdog0`, which the boards' generated devicetrees do not have, so the spike appends one to each board's `.dts` in the module's copy.

From the ROM, on the host (and the same on the other two):

```text
rom: zephyr: 27772 bytes to 0x80000000, jumping to 0x80000000
START - test_wdt
Testcase: test_wdt_no_callback
Waiting to restart MCU
rom: zephyr: 27772 bytes to 0x80000000, jumping to 0x80000000
Testcase: test_wdt_no_callback
Testcase passed
Testcase: test_wdt_callback_1
Waiting to restart MCU
rom: zephyr: 27772 bytes to 0x80000000, jumping to 0x80000000
Testcase: test_wdt_callback_1
    Assertion failed at ...test_wdt.c:495: test_wdt_callback_1() == TC_PASS is false
PROJECT EXECUTION FAILED
```

Three starts, two resets by the watchdog, and `.noinit` carried across both: the ROM reloads the image and leaves alone what the image does not cover, because the boot image is the ELF's file bytes and `.noinit` has none. ✅ That is the mechanism the test needs, and the model has it.

In the quick tier, with the image put in RAM by Python and no ROM, the same test comes back from its first reset, says `Testcase passed`, waits for its second, and is never heard from again: nothing more on the console in three seconds of simulated time. M14's step 11 said a quick-tier image does not survive a reset; this one survived one and not two. So the runner boots from the ROM unless told otherwise.

⚠️ **The failure is between Zephyr's test and Zephyr's driver.** `test_wdt_callback_1` installs a timeout with `WDT_FLAG_RESET_SOC` *and* a callback, and after the reset expects the callback to have run first and left a value. Zephyr's `wdt_sifive` has, at exactly that case, the comment "WDT supports global SoC reset but cannot callback", sets the watchdog to reset without interrupting, and returns success. The test provides for a driver that cannot (`-ENOTSUP` is "CB1 not supported on platform" and a pass), and the driver does not say so. A real SiFive board would fail the same way. It is an entry for [upstream.md](upstream.md) under Zephyr: have `wdt_sifive_install_timeout` return `-ENOTSUP` for a callback with a reset. Until then the suite is excluded, or run with the second and third cases switched off if the test has a setting for it, which was not looked for.

## 4. What it costs

On this Intel Mac, with everything in the devcontainer's image and the repository reached through Docker's bind mount:

| What | Wall time |
|---|---|
| A clean build of socpuppet for Linux (`build/linux`), once | about 10 minutes |
| One scenario, configure, build and run | about a minute |
| Of which the simulation | 1 to 6 seconds for most, 20 to 30 for the time-slicing scenarios |
| Fifteen suites on the host, 45 scenarios | 25 minutes |
| The same on the two 32-bit boards, 81 scenarios | 37 minutes |

Twister builds several scenarios at once (`JOBS: 14`), so the minute a scenario is CMake and the compiler through a slow file system, not the simulator. How much faster it is with the files on a local disk is question 7's.

What a CI job needs, and where it differs from today's: CI builds firmware in one job and runs it in another, on two operating systems, passing images between them. Twister builds and runs in one breath, so a `twister` job is both: the SDK, Zephyr and the venv that `firmware/build.sh` leaves (to cache, keyed on the two version strings), eleven more Python packages, a build of socpuppet, and `socpuppet run` on the `PATH`. The other way, `twister --build-only` in one job and a loop of our own over its output in another, was not tried: it would never exercise the platform file, `board.cmake` or twister's handler, which were the question.

Each run of twister moves the last output directory aside (`out.1`, `out.2`, ...), so a run of `--suites` leaves fifteen. A real recipe gives twister all the suites in one invocation. The spike ran them one at a time so that `-K` on one would not force the others onto boards they exclude.

## 5. A ztest suite of our own, beside the drivers

`spikes/twister/tests/drivers/syscon_reset_cause/` is a Zephyr application of four files: `CMakeLists.txt`, `prj.conf` (`CONFIG_ZTEST=y`, `CONFIG_SYSCON=y`), a `testcase.yaml` that allows the three boards, and a `main.c` with two cases against the system controller through Zephyr's `syscon` API, using the register names generated from `regs/system_controller.rdl`: the first start's cause is power-on, and the block's size is the register map's. `twister -T` on that directory found it, built it for each board and ran it: `socpuppet.drivers.syscon.reset_cause` passed on all three, two cases each. ✅

So a driver's tests can live beside the driver, be written in the framework every Zephyr developer knows, and be run by the same command as Zephyr's own. Nothing about the module had to change for it. Kept in the module, a suite would be found by `twister -T $(socpuppet zephyr-module)/tests`.

## 6. PMP is in the model, user mode is not on the core

DBT-RISE-RISCV has a PMP (physical memory protection, the RISC-V unit that lets machine mode fence off memory from less privileged code) as a layer in the memory path, `src/iss/mem/pmp.h`, with tests of its own under `contrib/fw/pmp-*`. The two cores socpuppet builds by default, `rv32imac_mp` and `rv64imac_mp` (`src/socpuppet/models/dbt_rise_cpu.cpp`), are the "m with PMP" registrations in `src/sysc/register_cores.cpp`: the layer is already stacked under every socpuppet CPU. What they lack is user mode: the hart behind them is `riscv_hart_m_p`, machine mode only, so Zephyr's `CONFIG_USERSPACE`, which runs threads in user mode behind PMP, has nowhere to run. DBT-RISE registers `rv32imac_mu` and `rv64gc_msu` with user mode, and the `_mu` ones without the PMP layer, so the change is a core name and a PMP layer in socpuppet's creator, not a model. The SoC's Kconfig would then `select RISCV_PMP`. It is a to-do, not a step of M21's: the suites that want it (`tests/kernel/mem_protect/*`, `tests/arch/riscv/userspace`) are the ones that would show whether the layer works.

## 7. Running it well: the file system was the cost

Added on 2026-10-11, after the first six, when the maintainer decided that twister belongs in CI and on demand locally, and asked how to run it well in both places. The question was put to the stopwatch: the same five suites on the host, eight scenarios, which the spike's first pass had run in 328 s as five invocations over Docker's bind mount.

| How | Wall time for the eight scenarios |
|---|---|
| Five invocations, everything on the bind mount (the spike's first pass) | 328 s |
| One invocation, everything on the bind mount | 193 s |
| One invocation, Zephyr, the SDK, the venv and the output on a Docker volume, cold: the copy and the venv first | 83 s |
| The same, warm, output cleaned | **35 s** |
| The same with `--no-clean`, nothing changed since | 19 s |
| The same with ccache, cold | 46 s |
| The same with ccache, warm (241 of 243 hits) | 44 s |
| The same with `-j 4` in place of 14 | 62 s |

Each figure is one run, on this Intel Mac with Docker Desktop given 14 CPUs and 32 GB. So:

- **The bind mount is the cost, and the volume removes it: ten times faster.** The compiler reading Zephyr's headers and the SDK through Docker's file sharing is where the minute went, not CMake's work and not the simulator. On a volume, a scenario is four seconds.
- **One invocation instead of one a suite saves 40%** on the bind mount, where each invocation pays again for twister's start, the module copy and the socpuppet build check. The recipe runs every suite in one, and the `-K` ones apart.
- **ccache does not pay.** Once the files are local, compiling is not the cost either, and ccache's own bookkeeping costs more than the 241 hits save. Not used.
- **`--no-clean` halves a rerun** when nothing changed, and twister's own help warns of inconsistencies when dependencies change. For "run the one that failed again" it is right; for a judgment it is not.
- **Four jobs, which is what a GitHub runner has, is 62 s for eight scenarios**, so about eight seconds a scenario and sixteen minutes for the spike's 126, if a runner's disk behaves like the volume. That is an estimate from a laptop and not a measurement on a runner, and it leaves out what the job does before twister: fetching the SDK and Zephyr, or restoring them from a cache (1.6 GB on disk), and building socpuppet, which the `test` job already pays.

What the recipe does now (`spikes/twister/twister.sh`), and what M21's step 6 inherits: on the Mac, a Docker volume `socpuppet-twister` holds a copy of Zephyr without its `.git`, the SDK, a venv made on the volume with the eleven extra packages, the module copy and twister's output; the copy is made again when the Zephyr or SDK version changes; only the verdicts and logs come back to `build/twister/out` (`twister.json`, the xunit files, each scenario's `handler.log` and `build.log`). `SOCPUPPET_TWISTER_BIND=1` and `SOCPUPPET_TWISTER_CCACHE=1` exist for the measurements above and nothing else.

For CI, two things Zephyr already provides: `--quarantine-list`, a YAML of scenarios or platforms to skip, each with a comment that twister copies into its reports, which is where "the watchdog suite is excluded, and why" belongs; and `zephyrproject-rtos/action-zephyr-setup@v1`, which installs the SDK and a west workspace on a GitHub runner, but wants a `west.yml`, which socpuppet does not have (`firmware/build.sh` makes a workspace of Zephyr alone). Whether to write one is a decision for the step, since it would also change how a user builds the firmware.
