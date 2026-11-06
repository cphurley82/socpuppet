# Handoff: the hang in `test_gdb.py` on QBox's CPU

**Source:** a Claude Code session on the maintainer's Intel Mac, the day after the nightly run below, which could not reproduce the hang (it showed on Apple silicon). 🚧 A working note for the branch `gdb-kernel-hang`: the branch's last commit deletes this file before the pull request.

## Goal

Nightly run [42222257914](https://github.com/cphurley82/socpuppet/actions/runs/42222257914/job/128007235743), job **Build and test with QBox's CPU (macos-15)**, hung in `tests/python/test_gdb.py::TestWhenADebuggerIsAttachedToABootingKernel::test_it_reads_the_kernels_banner_through_its_symbol` for 1800 s and was stopped (`1 failed, 1410 passed`). When this is done: the cause is found from the hung process's native stacks, fixed, held by a stress test in the nightly tier, recorded in `docs/upstream.md` and `docs/history/lessons.md`; and the pytest plugin dumps every thread's native stack whenever a platform test runs out of time, so the next hang on a CI machine we do not have diagnoses itself.

## Context

- The log's fault-handler dump shows **only the main thread**, in `platform.py:206 run` ← `test_gdb.py:1005` ← `run_with_debuggers`. The debugger's thread was gone, so its session had finished: breakpoint at `start_kernel`, continue, stop seen, the kernel's banner read by its virtual address, breakpoint removed, continue, hang-up. Then `board.platform.run(sp.ms(5000))` never returned, with no debugger attached and about 3.7 s of simulated time to go. No "could not connect" line on stderr (so not the held-up-run case of 1b4aba1).
- The sister test, `test_it_stops_at_start_kernel_where_the_map_says` (same scene minus the memory read), passed; the banner test passed on the same run's other three QBox machines (macos-26-intel, ubuntu-24.04, ubuntu-26.04) and in every nightly since it landed (9e13379): once in about 30 runs.
- This is the **third hang of one family**: `docs/history/lessons.md` lines 36–37 and `docs/upstream.md` §QBox record two races between SystemC's thread (QBox's CPU is a coroutine there) and QEMU's other threads, both fixed in our patches three days before this run: `cmake/patches/qbox-cpu-machine-state.patch` (a count of stops, `vm_stop_count`; commit f0c5b9c) and `cmake/patches/qbox-cpu-stop-arms-no-deadline.patch` with `cmake/patches/libqemu-vm-stop-state.patch` (`cpu_is_stopped`, no deadline for a run that only takes a stop; commit 28d8947). So this is a third cause, or a case those leave open. Both earlier ones were found from native stacks of the hung process (`gdb -p`, every thread), not by reading; a trace ring in memory caught the second.
- Read first: `AGENTS.md`, `docs/vision.md`, `docs/history/lessons.md` 34–37 and 142, `docs/upstream.md` §QBox (the entries on `vm_is_stopped`, the stop count and the quantum's deadline), `src/socpuppet/models/qbox_cpu.cpp` (`HoldForTheDebugger`, `OnTheMachineStoppedOrRunning`, `HoldTheClock`), the three patches above, QBox's loop as patched in `build/qbox/install/qemu-components/common/include/cpu.h` (`prepare_run_cpu`, `wait_for_work`, `sync_with_kernel`, `mainloop_thread_coroutine`), `tests/python/gdb_client.py`, `tests/python/test_gdb.py` lines 150–212 (`run_with_debuggers`), 773–801 (the existing stress test) and 950–1010 (the kernel tests), `python/socpuppet/pytest_plugin.py` (`_wait_for_child`, `_stop`) and `tests/python/test_pytest_plugin.py` (`TestWhenAPlatformTestRunsForLongerThanTheTimeout`).
- Setting up this Mac: `docs/setup.md` (Homebrew packages, `uv sync`), then `uv run tools/qbox.py` or the four commands in `docs/development.md#qbox-the-second-hart`; Linux's images are fetched, not built (`docs/linux.md`); `sudo DevToolsSecurity -enable` so lldb may attach to a process; `uv run python tools/doctor.py` says what is missing.

## Decisions

- Diagnose from native stacks before changing anything, because the lessons say reading did not find the two earlier hangs of this family and stacks did.
- The stress test of the kernel-banner scene is written first and is the regression test, because a race no test makes happen every time is held by a scene repeated in processes of its own, in the nightly tier (`SOCPUPPET_STRESS_RUNS`; `TestWhenADebuggerMeetsACpuHeldAfterItsReleaseAgainAndAgain` in `test_gdb.py` is the model).
- The pytest plugin learns to dump native stacks in this same change (the maintainer's choice), because the hang shows on CI's Apple silicon runner where nobody can attach a debugger by hand.
- A change to QBox or libqemu is a `git apply` file in `cmake/patches/` with an entry in `docs/upstream.md`, never an edit in `build/`, because that is how every borrowed fix is kept and sent upstream.
- Everything lands on the branch `gdb-kernel-hang`, cut from `main`, by a pull request the maintainer merges, because `main` is never pushed to directly.

## Constraints

- Test-first with `/tdd`; `/test-design-review` on each new test, `/software-design-review` once green; `uv run ctest --preset fast` at each step.
- Commits: one change each, a one-line header, a blank line, bullets; **no Claude attribution lines** (no Co-Authored-By, no session link, no "Generated with"). Tidy the commits before the branch lands, never after.
- Run clang-tidy before pushing C++ (`uv run python tools/ci.py tidy`): ctest skips it and CI fails on it.
- Markdown is one paragraph per line, never wrapped by hand; `uv run python tools/lint.py --fix` repairs what it can.
- Names in code stay the industry's; the puppet-show voice stays in prose; one joke a page, never in the sentence that carries the mechanism.
- A QBox patch edited is not applied to a QBox already built: delete `build/qbox` and run `uv run tools/build_qbox.py` again. The patches stack in `cmake/Dependencies.cmake`'s order (QBox's in file-name order).

## Suggested approach

1. **Native stacks in the plugin** (`python/socpuppet/pytest_plugin.py`, tests beside `TestWhenAPlatformTestRunsForLongerThanTheTimeout`). Specifications: (a) a timed-out platform test's failure carries every thread's native stack under its own heading, taken **before** `SIGABRT` while the process is still hung: `lldb --batch -p PID -o "thread backtrace all" -o detach` on macOS, `gdb -p PID -batch -ex "thread apply all bt"` on Linux, bounded by a constant and the debugger killed if it overruns; (b) with no debugger installed, one line saying which to install, the rest as today; (c) a debugger that cannot attach has its words quoted, then the abort as today, and the test for (a) skips on such a machine, naming `sudo DevToolsSecurity -enable`; (d) on Linux the child calls `prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY)` through `ctypes` in `pytest_configure`'s child branch (`PR_SET_PTRACER = 0x59616d61`), so GitHub's runners with `ptrace_scope = 1` let the attach through: lesson 36's `sitecustomize` trick, moved into the plugin. One sentence each in the plugin's module docstring, `docs/architecture.md` (the paragraph on `socpuppet_platform_timeout`), `docs/development.md`'s stress-test tip and lesson 36.
2. **The stress test**: `TestWhenADebuggerReadsTheBootingKernelsBannerAgainAndAgain` in `test_gdb.py`, marked `long`, `only_on_qbox`, `platform`, `parametrize("run", range(STRESS_RUNS))`, the banner test's scene through a helper both share. Time one run on this Mac, then `SOCPUPPET_STRESS_RUNS=100 SOCPUPPET_CPU=qbox_cpu uv run pytest -n auto -o socpuppet_platform_timeout=<three times one run> -k BannerAgainAndAgain tests/python/test_gdb.py`. A hang now reports with every thread's stack. If 300 runs pass, shorten the scene's `run()` to just past `start_kernel` (about 1.5 s simulated) and raise `-n` past the core count.
3. **Read the stacks** against the known shapes. (a) SystemC's thread in `HoldTheClock` → `sc_suspend_all` while QBox's loop sits in `wait_for_work`: the loop was never told the machine runs again (look at `m_machine_stopped`, `vm_stop_count`, QEMU's `runstate`). (b) SystemC's thread in `sync_with_kernel` → `m_qk->sync()` on a held clock: QEMU's clock warped ahead, a deadline armed for a run that took a stop. (c) Anything else: QEMU's gdb thread and main loop, and the client's `c` followed at once by `close()` (`gdb_client.py`, `run_with_debuggers`'s `finally`). When the stacks are not enough, a ring of trace lines in memory read out of the hung process (lesson 37).
4. **Fix** where the stacks point: a patch plus an `upstream.md` entry in the existing shape (Where / What is wrong / How to see it / What we do / Upstream fix / Kind / When it lands) and a line in `lessons.md`; or a change in `qbox_cpu.cpp`, which is ours. The stress test's docstring says the hit rate without the fix, as the existing one does.
5. **Verify and land**: `uv run ctest --preset fast`; the gdb tests under `SOCPUPPET_CPU=qbox_cpu`; 1000 or more stress runs clean; `uv run python tools/ci.py tidy`; `gh workflow run nightly.yml --ref gdb-kernel-hang` for the whole suite on CI's machines, macos-15 included (`gh run watch`); the two reviews; tidy the commits; delete this file in the last commit; open the pull request and hand it to the maintainer (`gh pr merge N --auto --rebase` is theirs).

## Open questions

- Whether the Air reproduces it at all: the rate on CI's macos-15 was about one in 30 whole-suite runs with three workers on the machine. If 1000 runs of the plain scene pass, vary the load (`-n` above the core count, the full `test_gdb.py` alongside) before concluding anything.
- Whether the memory read at a virtual address (the one thing the hung test does that its passing sister does not) matters, or only lengthens the window.
- How long lldb takes to attach to a process with QEMU in it, which sets the bound in specification 1(a).

## Out of scope

- The DBT-RISE CPU's debugger: the hang is QBox's.
- Raising `socpuppet_platform_timeout` or shortening the test's run to make the failure rarer: the product hangs, the test is right.
- The nightly's other recent failures (`test_the_clock_runs_well_ahead_of_the_wall_to_the_prompt` on the Intel Mac, the wheels) are separate.

---

**Kickoff prompt:** Read `HANDOFF.md` and finish it. Start by reading the files named in Context, in that order, and run `uv run python tools/doctor.py`; ask before deviating from the Decisions section.
