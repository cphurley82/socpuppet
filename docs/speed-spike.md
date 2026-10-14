# The speed spike: where to do the Linux work, and which CPU ships

This is the report for milestone M26 in [plan.md](plan.md). It opens with a recommendation on where to do the development that gets Linux booting, then one on the two decisions about what ships. Nothing that depends on either has been built.

**In one paragraph.** The host's core, DBT-RISE's interpreter, was timed on three loops on three machines and in seven environments, beside DBT-RISE's two translating backends where they build, QBox where it runs, and what a developer waits for in each place: a build from nothing, a rebuild after one file, and the `dev` suite. The MacBook Air, natively, is the fastest place to do everything: the fastest interpreter (41 million instructions a second), the quickest build (75 s), rebuild (4 s) and suite (61 s). The translating backends run the counted loop three to four times faster than the interpreter and the walking loop twice as fast, and each fails twenty to thirty of the hart's tests, on the very things a kernel leans on. So the recommendation is the Air, natively, on the interpreter, with LLVM on the same machine (Homebrew's, 169 million instructions a second) for the day a boot is too long to wait for; the interpreter stays the wheel's CPU; and nothing faster is offered beside it until the backends pass the hart's suite.

## The recommendation

**Do the Linux work (M23, M25, M20) on the MacBook Air, natively, on the interpreter.**

- 🏎️ **It is the fastest machine at everything measured**, by a wide margin over the Mac Pro and a clear one over the Ubuntu box. The interpreter runs the counted loop at 41 million instructions a second there, against 33 on the Ubuntu box and 17 on the Mac Pro, and the walking loop at 24 against 20 and 7. A build from nothing takes 75 s (104 and 180), a rebuild after touching the CPU's adapter 4 s (9 and 19), and the `dev` suite 61 s (66 and 171). Those three are what a developer waits for a hundred times a day, and the Air waits least.
- 🎯 **The interpreter is the only CPU the suite vouches for.** All 925 tests pass on it in every one of the seven environments. asmjit fails 29 of them and LLVM 21, and the failures are not corners: the floating-point state a kernel reads to know whether to save a program's registers, the reservation a kernel's locks are built on, the page fault a kernel takes to map a page late, a misaligned access, and under asmjit an interrupt that arrives at a load. A kernel brought up on a backend with those wrong would be debugged for the backend's faults as much as for its own.
- 🐧 **Linux is Linux everywhere here.** The Ubuntu box's container and its native column agree to within a few per cent, so GCC 13 against GCC 15 is not a variable, and neither is macOS against Linux for what the core does: every environment passed the same tests. The one thing the Macs cannot do natively is asmjit, which makes x86-64 code, and the Air cannot do it at all except under Rosetta.

**When a boot is too long to wait for: LLVM, natively on the Air.** Against Homebrew's LLVM 23 (one patch of ten lines, below) it runs the counted loop at 169 million instructions a second, the hits loop at 113 and the walking loop at 53: the fastest DBT-RISE core measured anywhere, faster than asmjit natively on the Ubuntu box, and the build from nothing takes 93 s. In the Air's arm64 container, with Debian's LLVM 19, it is 141, 102 and 52. It is for watching a boot go by, not for deciding what the hart did: 21 tests fail on it, and in the container six of the Python examples that boot Zephyr on the host do not reach their greeting. QBox is twice as fast again on straight code and is the one CPU here that has run a kernel, but it is not a CPU of socpuppet's yet: its wrapper runs nothing of the suite, and the SystemC it brings cannot be linked with socpuppet's.

**Second choice: the Ubuntu box, natively.** Its development loop is nearly the Air's (104 s, 9 s, 66 s), it is the one machine where asmjit, LLVM 19, 20 and 21, QBox and plain QEMU all run with nothing emulated, and it is where this spike's own backend work was done. Its one drawback is the interpreter, a quarter slower than the Air's.

**Not the Mac Pro.** It is last at everything: the interpreter at 17 million instructions a second, a build from nothing in 180 s, and the suite in 171 s, of which the C++ tests alone take 146 s where the Ubuntu box takes 4 s, because each test is a process and starting one is dear there. Its container is slower still (473 s and 267 s). The Air runs the x86-64 container under Rosetta, an emulated CPU, faster than the Mac Pro runs natively.

## The two decisions about what ships

**The wheel's CPU: the interpreter, as it is.** It is the only core that builds everywhere the wheel does, including the Apple silicon runner, and the only one that passes the hart's suite. Its extension is 12 to 13 MB on macOS.

**A faster CPU beside it, built from source: not yet, and LLVM when it is.** Each translating backend is behind `SOCPUPPET_DBT_RISE_BACKENDS` and stays off by default. What each would cost and what each gives:

- **asmjit** adds one zlib-licensed library fetched at a pinned commit, 3.9 MB to the macOS extension, and makes x86-64 code only, so it could never be the Air's or the arm64 runner's. It is four times the interpreter on the counted loop and twice on the walking one, and fails 29 tests.
- **LLVM** makes code for whatever host it runs on, so it is the one backend every machine here can have, and it is the fastest. It wants an LLVM development package the wheel cannot assume (`llvm-19-dev` on Ubuntu, `llvm@22` from Homebrew), and the extension links LLVM's shared library (1.7 MB more on macOS, with the dylib beside it; 28 MB more in the arm64 container, where it is linked in). It fails 21 tests, fewer than asmjit, and the interrupt tests among asmjit's failures pass on it.
- **QBox** is QEMU inside SystemC, GPL-2.0, and a build of its own from source. Its rows are below.

The failures are one thing, not twenty-nine: M22's fifteen patches mended the interpreter, or the hart where the interpreter fetches, and a translating backend has its own copy of every instruction's behaviour and fetches another way. They are listed in [upstream.md](upstream.md) under "What the interpreter was mended for, the translating backends were not", with the fix, which is each patch again in DBT-RISE's generator so that every backend has it. Until then a backend is a thing to time a boot on and not to trust one to, and the to-do in [plan.md](plan.md) says so.

## The question

A kernel's boot to a prompt is hundreds of millions of instructions, and nobody had measured what the host's core makes of one, what paging costs it, or what any other way of running the same instructions would give. M1's spike had one figure, 44 million instructions a second on the Air for a loop of two instructions with paging off, and said of it that such a loop flatters an interpreter.

Asked by the maintainer when the spike was planned: the first question is not what ships but where to do the work. Three machines are to hand, each with Docker, and not every CPU option builds or runs on every one. So the report's first answer names a machine, an environment and a CPU for the development that gets Linux booting, and the two decisions M26 was written for come second.

## The machines

| | Mac Pro (2019) | MacBook Air | Ubuntu box |
|---|---|---|---|
| CPU, RAM | Intel Xeon W-3223, 16 threads, 48 GB | Apple M4, 10 cores, 32 GB | AMD Ryzen 5 7600X3D, 12 threads, 26 GB |
| OS, compiler | macOS 26.6, Apple clang 21 | macOS 26.7, Apple clang 21 | Ubuntu 26.04, GCC 15 |
| Docker | x86-64 Linux VM, 14 CPUs | arm64 Linux VM, 10 CPUs, 16 GB; x86-64 containers under Rosetta | native, 12 CPUs |
| LLVM | Homebrew `llvm@22` | none natively; apt `llvm-19` in the container | apt `llvm-19`, `-20`, `-21` |
| QEMU | none | none | apt 10.2, no plugins |

Every container is the devcontainer's image, Ubuntu 24.04 with GCC 13, which is what CI builds in. The environments have fixed names, so that a line of results says where it came from: `native-macos-x86_64` and `docker-amd64-on-macpro`; `native-macos-arm64`, `docker-arm64-on-air` and `docker-amd64-rosetta-on-air`; `native-linux-x86_64` and `docker-amd64-on-ubuntu`.

## What was measured

Three loops, each made of `tests/cpp/support/riscv_program.h` and nothing else, run on the host's core with its RAM behind a probe that counts transactions, so that each test can assert it ran by direct memory access ([spikes/speed/README.md](../spikes/speed/README.md)):

| Loop | What it does | What it stands for |
|---|---|---|
| `counted` | M1's loop: count down from 2²⁴, two instructions a time round, paging off. 33.5 million instructions | The best case, which flatters an interpreter |
| `walks` | Supervisor mode under Sv39 loads from 32 pages in turn, and each round ends with `sfence.vma`, so that every load of the next round walks the page tables. 17.6 million instructions, 4.3 million walks | The worst case: a kernel that has just switched address spaces |
| `hits` | The same with a `nop` for the fence, so every translation after the first round is one the hart kept | What paging costs when it costs least |

Each loop ran three times in each cell, one test at a time, nothing else running, and the tables show the median. Beside them, in each environment, the developer's three waits: a configure-and-build from an empty tree with the dependencies already fetched, a rebuild after touching `src/socpuppet/models/dbt_rise_cpu.cpp`, and the `dev` suite (C++, Python and lint, eight at a time). A backend is built into a tree of its own as the build's default, so that the whole suite runs on it with no test touched.

The tables below are what `python3 -I spikes/speed/collect.py` prints from `spikes/speed/results/` at commit `the commit that closes M26 (the results are in `spikes/speed/results/`, one file a column)`.

## Results at a glance

| CPU | Mac Pro, macOS | Mac Pro, Docker x86-64 | Air, macOS | Air, Docker arm64 | Air, Docker x86-64 (Rosetta) | Ubuntu box, Linux | Ubuntu box, Docker x86-64 |
|---|---|---|---|---|---|---|---|
| DBT-RISE interpreter | ✅ suite 925/925 | ✅ suite 925/925 | ✅ suite 925/925 | ✅ suite 925/925 | ✅ suite 925/925 | ✅ suite 925/925 | ✅ suite 925/925 |
| DBT-RISE asmjit | ✅ suite 898/928 | ✅ suite 898/928 | 🚧 | 🚧 | ✅ | ✅ suite 898/928 | ✅ |
| DBT-RISE LLVM 19 | 🚧 | ✅ suite 906/928 | 🚧 | ✅ suite 900/928 | 🚧 | ✅ suite 906/928 | ✅ suite 906/928 |
| DBT-RISE LLVM 21 | 🚧 | 🚧 | 🚧 | 🚧 | 🚧 | ✅ suite 906/928 | 🚧 |
| DBT-RISE LLVM 22 | ✅ suite 906/928 | 🚧 | 🚧 | 🚧 | 🚧 | 🚧 | 🚧 |
| DBT-RISE LLVM 23 | 🚧 | 🚧 | ✅ suite 905/928 | 🚧 | 🚧 | 🚧 | 🚧 |
| QBox, repeatable | ❌ build-failed | ✅ | ❌ build-failed | ✅ | 🚧 | ✅ | 🚧 |
| QBox, threaded | 🚧 | ❌ speed-failed | 🚧 | ❌ speed-failed | 🚧 | ❌ speed-failed | 🚧 |

🚧 is a cell that was not tried, ❌ one that was tried and failed, with why. An LLVM row is one version of LLVM: DBT-RISE is written against 19, and 21 and 22 built with no source changes.

## Speed

| Where | CPU | Counted (M/s) | Hits (M/s) | Walks (M/s) | Walks (M walks/s) | Runs |
|---|---|---|---|---|---|---|
| Mac Pro, macOS | DBT-RISE interpreter | 16.7 | 11.3 | 7.0 | 1.7 | 5 |
| Mac Pro, macOS | DBT-RISE asmjit | 69.2 | 43.1 | 13.8 | 3.4 | 3 |
| Mac Pro, macOS | DBT-RISE LLVM 22 | 67.8 | 40.8 | 13.1 | 3.2 | 3 |
| Mac Pro, Docker x86-64 | DBT-RISE interpreter | 15.0 | 11.0 | 8.6 | 2.1 | 3 |
| Mac Pro, Docker x86-64 | DBT-RISE asmjit | 78.9 | 48.0 | 21.5 | 5.3 | 3 |
| Mac Pro, Docker x86-64 | DBT-RISE LLVM 19 | 76.5 | 46.0 | 20.9 | 5.2 | 3 |
| Mac Pro, Docker x86-64 | QBox, repeatable | 336.9 | 452.7 | 10.5 | 2.6 | 1 |
| Air, macOS | DBT-RISE interpreter | 41.0 | 31.6 | 23.8 | 5.9 | 5 |
| Air, macOS | DBT-RISE LLVM 23 | 169.0 | 112.9 | 53.3 | 13.1 | 3 |
| Air, Docker arm64 | DBT-RISE interpreter | 39.6 | 30.5 | 24.3 | 6.0 | 3 |
| Air, Docker arm64 | DBT-RISE LLVM 19 | 141.3 | 101.9 | 51.6 | 12.7 | 3 |
| Air, Docker arm64 | QBox, repeatable | 358.3 | 581.8 | 26.6 | 6.5 | 2 |
| Air, Docker x86-64 (Rosetta) | DBT-RISE interpreter | 24.3 | 18.7 | 14.3 | 3.5 | 3 |
| Air, Docker x86-64 (Rosetta) | DBT-RISE asmjit | 47.6 | 18.4 | 17.7 | 4.3 | 3 |
| Ubuntu box, Linux | DBT-RISE interpreter | 32.5 | 24.7 | 19.7 | 4.8 | 3 |
| Ubuntu box, Linux | DBT-RISE asmjit | 133.3 | 84.1 | 44.3 | 10.9 | 3 |
| Ubuntu box, Linux | DBT-RISE LLVM 19 | 122.9 | 77.3 | 43.3 | 10.7 | 3 |
| Ubuntu box, Linux | DBT-RISE LLVM 21 | 123.4 | 77.1 | 43.0 | 10.6 | 3 |
| Ubuntu box, Linux | QBox, repeatable | 375.4 | 588.5 | 22.7 | 5.6 | 2 |
| Ubuntu box, Docker x86-64 | DBT-RISE interpreter | 32.0 | 25.0 | 19.4 | 4.8 | 3 |
| Ubuntu box, Docker x86-64 | DBT-RISE asmjit | 144.0 | 89.8 | 46.6 | 11.5 | 3 |
| Ubuntu box, Docker x86-64 | DBT-RISE LLVM 19 | 124.4 | 82.7 | 43.6 | 10.7 | 3 |

What the numbers say:

- **Paging costs the interpreter 40 % when every load walks the tables, and a quarter when the TLB hits.** The same proportions on every machine.
- **A translating backend gains most where an interpreter loses most.** asmjit and LLVM run the counted loop three to four times faster than the interpreter and the walking loop about twice as fast: a walk is a run of loads the translated code has to make too, and the translator cannot remove the `sfence.vma`.
- **asmjit under Rosetta is a JIT's x86-64 code under Apple's translator**: 48 million on the counted loop, twice the interpreter there and a third of asmjit on the Ubuntu box, and no faster than the interpreter on the paging loops. Its suite could not be completed: ctest died at the same test in three runs, with no summary, which reads as the Docker VM ending the container.
- **The Air's container costs nothing.** The interpreter runs at the same rate in it as natively, and the Rosetta container is a third slower than that, and still faster than the Mac Pro natively.
- **The quantum changes nothing for the interpreter**: the counted loop runs at the same rate at the boards' 100 µs and at M1's 1 ms.
- **M1's 44 million on the Air is 41 now**, after M22's fifteen patches, which put a translation and a check in front of every fetch.

## The development loop

| Where | Machine | Build from nothing (s) | Rebuild after one file (s) | dev suite (s) | Tests passed |
|---|---|---|---|---|---|
| Mac Pro, macOS | Intel(R) Xeon(R) W-3223 CPU @ 3.50GHz, 16 threads | 180 | 18.9 | 171 | 925 of 925 |
| Mac Pro, Docker x86-64 | Intel(R) Xeon(R) W-3223 CPU @ 3.50GHz, 14 threads | 473 | 35.9 | 267 | 925 of 925 |
| Air, macOS | Apple M4, 10 threads | 75 | 4.3 | 61 | 925 of 925 |
| Air, Docker arm64 | aarch64, 10 threads | 172 | 10.9 | 105 | 925 of 925 |
| Air, Docker x86-64 (Rosetta) | VirtualApple @ 2.50GHz, 10 threads | 369 | 16.3 | 243 | 925 of 925 |
| Ubuntu box, Linux | AMD Ryzen 5 7600X3D 6-Core Processor, 12 threads | 104 | 8.8 | 66 | 925 of 925 |
| Ubuntu box, Docker x86-64 | AMD Ryzen 5 7600X3D 6-Core Processor, 12 threads | 102 | 8.5 | 62 | 925 of 925 |

The Mac Pro and the Ubuntu box skip the seven firmware examples that want an image built on the machine; the Air runs them. 🎓 The Mac Pro's C++ tests take 146 s where the Ubuntu box's take 4 s and the Air's 9: each is a process of its own, and starting one costs far more there.

## The backends

| CPU | Where | dev suite passed | Failed | Extension, MB more |
|---|---|---|---|---|
| DBT-RISE asmjit | Mac Pro, Docker x86-64 | 898 of 928 | 29 C++ tests, pytest | +70.9 |
| DBT-RISE asmjit | Ubuntu box, Linux | 898 of 928 | 29 C++ tests, pytest | - |
| DBT-RISE asmjit | Mac Pro, macOS | 898 of 928 | 29 C++ tests, pytest | +3.9 |
| DBT-RISE LLVM 19 | Mac Pro, Docker x86-64 | 906 of 928 | 21 C++ tests, pytest | +28.1 |
| DBT-RISE LLVM 19 | Ubuntu box, Docker x86-64 | 906 of 928 | 21 C++ tests, pytest | +28.1 |
| DBT-RISE LLVM 19 | Air, Docker arm64 | 900 of 928 | 21 C++ tests, pytest, example_host_hello, example_host_and_ssd_hello, example_chiplet_host_hello, example_shell_from_python, example_full_bootchain, example_boot_from_flash | +27.6 |
| DBT-RISE LLVM 19 | Ubuntu box, Linux | 906 of 928 | 21 C++ tests, pytest | +28.5 |
| DBT-RISE LLVM 21 | Ubuntu box, Linux | 906 of 928 | 21 C++ tests, pytest | +28.7 |
| DBT-RISE LLVM 22 | Mac Pro, macOS | 906 of 928 | 21 C++ tests, pytest | +1.7 |
| DBT-RISE LLVM 23 | Air, macOS | 905 of 928 | 21 C++ tests, pytest, lint | +1.5 |

⚠️ "MB more" is honest only on macOS. The Linux extensions carry their debug information, and a backend's generated cores carry a great deal of it. On macOS asmjit adds 3.9 MB and LLVM 1.5 to 1.7 MB plus the LLVM dylib it loads.

The failures, grouped, with the test's name standing for what it holds:

| What fails | asmjit | LLVM | Why |
|---|---|---|---|
| The floating-point state: an instruction with `FS` off is no illegal instruction, and a use never marks it dirty (`fp-status`) | 11 | 11 | M22 step 6 put the check where the interpreter fetches; a backend translates blocks and never passes there |
| An interrupt that arrives at a load, or while the core sleeps in supervisor mode, and the IMSIC's handlers (`interrupt-at-instruction`, `supervisor-interrupts`) | 9 | 0 | asmjit's generated core takes the interrupt as the borrowed one did; LLVM's takes it as the patched interpreter does |
| A store-conditional with no reservation succeeds (`one-reservation`) | 4 | 4 | The fix is in the interpreter's `sc` |
| A jump to a page that is not mapped takes no page fault, in supervisor and in user mode, and under asmjit an instruction at a page's end with the next page unmapped hangs (`translate-fetches`, `fetch-ends-page`) | 3 | 2 | A backend fetches with a debug read, which the MMU translates as a load and which does not stop at a page's end. The hang is the test that times out |
| A misaligned word in supervisor mode (`misaligned-atomic`) | 2 | 2 | The fix is in the hart where the interpreter fetches |
| A single-precision load or store through an address above 4 GiB | 0 | 2 | `flw` and `fsw` cut their address to 32 bits in every generated core; M22 mended the interpreter's |
| pytest | ✗ | ✗ | On the Macs it times out. On Linux, under asmjit the first GDB test on the host board never gets an answer, and with GDB skipped one test fails (a run interrupted from the keyboard); under LLVM five fail: a program using a floating-point register, the host's `time` read, and the three host-board GDB tests. A debugger's hooks are in the interpreter's loop, which a translated block never passes |

⚠️ The hung test is why `run.sh` sweeps a suite's processes when it ends: one was found five hours later, still at 100 % of a core, under the timings of the next column.

What each took to build, within M1's allowance of four patches of about twenty lines a backend:

- **asmjit: four patches and a fetch.** The JIT helper that DBT-RISE-Core's backends share declares a `wait()` that collides with POSIX on macOS, which is why every build left it out; it is `iss_wait` now, in Core and in the two generated cores that name it (two patches), and the linker is told to keep it, since a static library drops a symbol nothing it links refers to. The generated cores use `__int128` traits that only libstdc++ has, so the third patch guards them. asmjit itself is fetched at a pinned commit with `OVERRIDE_FIND_PACKAGE`, the way Core looks for it.
- **LLVM: five patches and a workaround, two of asmjit's shared.** The core is registered under the name the SystemC wrapper looks up (`rv64gc_msu:llvm`). LLVM's JIT is initialised before the first core asks for it. Block arguments were `i8` where they are pointers, which LLVM 19 and later refuse. `wfi` in both backends called the helper by the old name. And Debian's LLVM package calls `pkg_check_modules` without loading `FindPkgConfig`, which our configure loads for it. LLVM 21 and 22 then built with no change from 19; LLVM 23 removed `CreateGlobalStringPtr`, which the generated cores call 661 times, and the fifth patch gives the builder the name back in ten lines of Core. The Air's LLVM 23 was the maintainer's ask, past the four of the allowance.

## QBox

QBox is QEMU's RISC-V CPU inside SystemC, behind the CPU slot M1's spike built for it (`spikes/speed/qbox/`), with the same three loops on a RAM that grants direct access. It builds at the commit M12's spike builds, as C++20 with the NPU spike's three source patches, and without virgl and virCL, which neither Ubuntu 26.04's glibc nor Homebrew would compile for it. Natively on the Ubuntu box it built in 221 s; in the Air's arm64 container it built; natively on the Macs it did not, one missing Homebrew package at a time (`libzip`, `epoxy`, `sdl2`, and the attempt after `sdl2` had not finished when this was written), and in the Mac Pro's container the first attempt failed with its log lost and the second had not finished.

What it measured, in its repeatable configuration (QEMU as a coroutine on the SystemC thread, counting instructions for time): **350 to 360 million instructions a second on the counted loop and 580 to 590 on the hits loop, about nine times the interpreter and two to three times LLVM, and 23 to 27 million on the walking loop, slower than every DBT-RISE core but the Mac Pro's interpreter.** 🎓 QEMU keeps translated code keyed by physical address and throws it all away on `sfence.vma`, and the walking loop fences every round, so there it translates the loop again 2¹⁷ times. A kernel fences far less often than that, so its boot would land near the hits figure. The threaded configuration (QEMU on threads of its own, nothing keeping it in step with SystemC) crashed on every loop, on both machines, and has no row; M1 measured it at 3,800 million on its own, and it was never repeatable.

What QBox cannot be measured on: `cpu_test.cpp`, the bus-master contract and the Python suite, since its SystemC cannot be linked with socpuppet's. Its CPU tests are M1's candidate suite, which is the to-do it already was. And it is GPL-2.0, so it is a build from source beside the wheel, never in it.

## The projection

A boot to the shell is 1849 million instructions (median of 6).

| Where | CPU | At the counted rate (s) | At the walking rate (s) |
|---|---|---|---|
| Mac Pro, macOS | DBT-RISE interpreter | 111 | 262 |
| Mac Pro, macOS | DBT-RISE asmjit | 27 | 134 |
| Mac Pro, macOS | DBT-RISE LLVM 22 | 27 | 141 |
| Mac Pro, Docker x86-64 | DBT-RISE interpreter | 123 | 216 |
| Mac Pro, Docker x86-64 | DBT-RISE asmjit | 23 | 86 |
| Mac Pro, Docker x86-64 | DBT-RISE LLVM 19 | 24 | 88 |
| Mac Pro, Docker x86-64 | QBox, repeatable | 5 | 176 |
| Air, macOS | DBT-RISE interpreter | 45 | 78 |
| Air, macOS | DBT-RISE LLVM 23 | 11 | 35 |
| Air, Docker arm64 | DBT-RISE interpreter | 47 | 76 |
| Air, Docker arm64 | DBT-RISE LLVM 19 | 13 | 36 |
| Air, Docker arm64 | QBox, repeatable | 5 | 70 |
| Air, Docker x86-64 (Rosetta) | DBT-RISE interpreter | 76 | 130 |
| Air, Docker x86-64 (Rosetta) | DBT-RISE asmjit | 39 | 105 |
| Ubuntu box, Linux | DBT-RISE interpreter | 57 | 94 |
| Ubuntu box, Linux | DBT-RISE asmjit | 14 | 42 |
| Ubuntu box, Linux | DBT-RISE LLVM 19 | 15 | 43 |
| Ubuntu box, Linux | DBT-RISE LLVM 21 | 15 | 43 |
| Ubuntu box, Linux | QBox, repeatable | 5 | 81 |
| Ubuntu box, Docker x86-64 | DBT-RISE interpreter | 58 | 95 |
| Ubuntu box, Docker x86-64 | DBT-RISE asmjit | 13 | 40 |
| Ubuntu box, Docker x86-64 | DBT-RISE LLVM 19 | 15 | 42 |
| Air, macOS | Plain QEMU, as measured | 2.0 | - |
| Ubuntu box, Linux | Plain QEMU, as measured | 2.9 | - |

⚠️ It is a distribution kernel with a 41 MB initrd, booted by OpenSBI on QEMU's devicetree with one hart, so its count is an upper bound for M20's boot of a small kernel with a busybox in memory. And the walking rate is the floor of a kernel's rate, not what a kernel runs at: a kernel walks the tables after every change of address space and hits its TLB the rest of the time, so its boot lands between the two columns and nearer the first.

## Not exercised

- **LLVM 20 on the Ubuntu box**, between two versions that worked, and LLVM 23 anywhere but the Air.
- **A boot on a backend.** The Python examples that boot Zephyr on the host ran as part of the suite; nothing bigger ran on asmjit or LLVM, and nothing ran Linux on anything of socpuppet's.
- **The 32-bit cores on a backend.** No translating backend has a core with physical memory protection, so the two controllers and the plain `rv64gc` run the interpreter whatever the build's default, and the build gives way to it there.
- **TinyCC**, which has no 64-bit core.
- **QBox natively on macOS**, which stopped at Homebrew's packages (above), and QBox threaded, which crashed.
- **More than one run of the suite per backend.** The pass and fail counts were the same on every machine a backend ran on, so a second run on each was not taken.
- **A real workload on the speed tests.** Three loops, none of them a kernel; the projection is the bridge.

## Decisions

Left for the maintainer, with the recommendation beside each in the table of [decisions deliberately left open](plan.md#decisions-deliberately-left-open):

1. **Where to do the Linux work**: the Air, natively, on the interpreter; LLVM in its arm64 container for a long boot.
2. **The wheel's CPU**: the interpreter, as it is.
3. **A faster CPU beside it**: none yet. LLVM, built from source against a system LLVM, when the backends pass the hart's suite, which is the to-do; QBox only once it is a CPU of socpuppet's, which is the other.

What stays from the spike: `spikes/speed/` and its results, so that every later change to the core can be timed against them ([spikes/speed/README.md](../spikes/speed/README.md)); the backends behind `SOCPUPPET_DBT_RISE_BACKENDS`, off; `DbtRiseCpu` taking a backend's name from C++ and refusing one its build has no core for; and the nine patches and the entries in [upstream.md](upstream.md).
