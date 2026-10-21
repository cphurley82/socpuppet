# CPU (QBox)

`sp.QboxCpu(xlen=64, reset_vector=...)` · C++ `socpuppet::QboxCpu` · registry name `qbox_cpu` · only in a build with QBox

## What it stands for

The same RISC-V processor core as the [DBT-RISE CPU](dbt-rise-cpu.md)'s RV64GC with supervisor and user mode, played by a different actor. 🎓 The model is [QEMU](https://www.qemu.org)'s RISC-V CPU, inside SystemC by way of Qualcomm's [QBox](https://github.com/qualcomm/qbox). Where DBT-RISE interprets each instruction as it comes, QEMU **translates**: the first time it meets a stretch of RISC-V code it writes the host's own instructions that do the same, and from then on runs those. So it is several times faster on code that loops.

💡 It is here as a **second opinion**. Two harts written by different people rarely share a mistake. When firmware works on one and not the other, the difference says where to look, before anyone suspects the firmware or the devices. M27 put it in for the Linux work that follows ([roadmap.md](../roadmap.md)).

## Getting it

QEMU is GPL-2.0, so it is never in socpuppet's wheel. Whoever wants it builds it:

```sh
uv run tools/build_qbox.py      # QBox and its QEMU, into build/qbox/install: about five minutes
uv run cmake --preset qbox      # socpuppet with it, in build/qbox-dev
uv run cmake --build --preset qbox
uv run ctest --preset qbox      # everything, with the hart's tests on QBox's CPU
```

[setup.md](../setup.md) lists the packages the tool needs, on Linux and on a Mac, and on a Mac the same four commands can run in the devcontainer's image instead, through `tools/devcontainer.py`. A build without QBox still knows the name `qbox_cpu`, and refuses it with how to build one.

⚠️ A build with QBox links socpuppet to QBox's own SystemC and CCI, which are shared libraries, because one program can hold only one SystemC kernel. The build without QBox fetches the same SystemC commit and links it statically, so the two run the same kernel.

## What it does

```python
cpu = platform.add("cpu", sp.QboxCpu(xlen=64, reset_vector=0x8000_0000))
board = host(cpu="qbox_cpu")        # or SOCPUPPET_CPU=qbox_cpu for every host
```

- **RV64GC with supervisor and user mode**, and nothing else: 64 bits only, `isa="gc"`, `modes="msu"`. A 32-bit CPU is a `DbtRiseCpu`.
- **No Sstc**, as the DBT-RISE CPU has none. QEMU's hart would have it: a timer compare of supervisor mode's own, `stimecmp`, which QEMU times with its own ACLINT. The timer here is socpuppet's, outside QEMU, and QEMU read the frequency from the wrong object and divided by it: the first `set_timer` under OpenSBI ended the process ([upstream.md](../upstream.md)). So the adapter switches it off, and supervisor mode's timer is the machine timer's, set by OpenSBI through `mtimecmp`.
- **The same ports as the DBT-RISE CPU**, so it fits wherever that one does: `socket`, `time` from a [machine timer](machine-timer.md), `csr` to an [IMSIC](imsic.md), and `irq`, `timer_irq`, `supervisor_irq` and `reset`. The host board is the same around either, devicetree and all.
- **Picked by name or by the environment.** `host(cpu="qbox_cpu")` gives the host this CPU, and with no `cpu` named the host has the one `SOCPUPPET_CPU` names: `qbox_cpu` or `dbt_rise_cpu`. So one variable runs a whole suite's boots on the other hart, and twister's runs too (`socpuppet run` has `--cpu` as well).
- **Repeatable.** QEMU runs as a coroutine on SystemC's own thread and counts instructions for time (QEMU's `icount`), so two runs of one program do the same thing at the same simulated times.
- **Counts 128 ns for each instruction**, where the DBT-RISE CPU counts 100. QEMU counts in powers of two of a nanosecond, and 2⁷ is the nearest. Its own default, 1 ns, made firmware that waits by spinning spin a hundred times as many instructions for the same wait, and Zephyr's timer and scheduler suites ran out of twister's time. ⚠️ A test that counts timer ticks per instruction expects DBT-RISE's figure.
- **Boots UEFI with paging in Sv57**, where the DBT-RISE CPU has Sv39: EDK2 asks for the biggest mode first and keeps what `satp` reads back. To its shell is 550 million instructions on either hart, counted from each one's clock, which is the check that this one's clock counts instructions ([speed-spike.md](../history/speed-spike.md#a-boot-that-ran-opensbi-and-uefi-to-the-shell-m28)).
- **A debugger, QEMU's own.** `sp.QboxCpu(gdb_port=)`, or `host(cpu="qbox_cpu", gdb_port=)`, gives the CPU QEMU's GDB server on the port, and the CPU is held before its first instruction until the debugger says continue, as the DBT-RISE CPU waits for its own; a debugger that attaches later pauses the CPU where it is. ⚠️ The port opens when the run starts and the CPU is held, not as the platform is built: start the run, then attach, which is the order [boot-your-firmware.md](../boot-your-firmware.md) gives anyway. 🎓 QEMU's server reads memory the way the CPU would, through its address translation, so a kernel's symbols, which are virtual addresses, work as they are. A stopped CPU stops the whole simulation, as with the other CPU: time stands still until the debugger continues, whether the CPU waits at its first instruction, sits at a breakpoint or was paused. QEMU tells QBox when its machine stops and runs again, through a patch to each of them ([upstream.md](../upstream.md#the-platform-is-never-told-that-the-debugger-has-stopped-qemus-machine)). ⚠️ Told to continue with a breakpoint where it stands, QEMU's CPU stops at it again. GDB takes its breakpoints out at every stop, so it never sees this; a client of your own has to do the same. QEMU's server has no `monitor sysc print_time`, which is DBT-RISE's. The debugger tests (`tests/python/test_gdb.py`) run on this CPU under `ctest --preset qbox`; what it took is in [upstream.md](../upstream.md#qbox).
- **An instruction trace, QEMU's own, through the debugger.** QEMU's monitor commands work through GDB's `monitor`, and three of them log the address of every instruction the CPU runs, from wherever the debugger asks:

  ```text
  (gdb) monitor logfile /tmp/trace.log
  (gdb) monitor one-insn-per-tb on
  (gdb) monitor log exec,nochain
  (gdb) continue
  ```

  🧵 `socpuppet.qemu_trace.pcs(text)` reads the addresses out of the log, one to an instruction, so two runs can be compared and the first instruction where they part found. 💡 A trace of a whole Linux boot is billions of lines: set a breakpoint near the trouble first, and switch the log on there (`monitor log none` switches it off). The DBT-RISE CPU has no such trace yet (its `enable_disass` exists, but goes to its own logger and is not a parameter of ours).
- **Holds to the bus-master contract** (`tests/cpp/contracts/bus_master_contract.h`), as every CPU and the scripted stand-in do, and to the hart's own suite (`tests/cpp/platform/cpu_test.cpp`), apart from what is below.

## What makes it fast

🎓 The same two things as the DBT-RISE CPU (the direct memory interface and temporal decoupling, both on [its page](dbt-rise-cpu.md#what-makes-it-fast)), plus translation. On the A51 (an Intel Core Ultra 9 285K, Ubuntu 26.04) at the boards' 100 µs quantum, through socpuppet's own platform, it ran M26's three loops at about 280 million instructions a second counting down, 610 million through pages it had already walked, and 18 million when every load is a walk of the page tables ([speed-spike.md](../history/speed-spike.md)). A boot of OpenSBI and UEFI to the shell ran at 343 million, 1.6 s on the wall where the interpreter took 34; 🐧 Linux to its prompt took 6 s where the interpreter took 75 ([linux.md](../linux.md)).

## What it does differently

The hart's suite runs on it with `ctest --preset qbox`, and what it does not pass is skipped there with the reason, from one table (`tests/cpp/support/qbox_fates.h`), so that a new failure stands out. 38 of the suite's cases, in these groups:

| What | Why | Whose |
|---|---|---|
| The 32-bit tests | QBox's CPU here is 64-bit only | by design |
| Timer ticks counted per instruction, and a loop timed to outlast a millisecond | 128 ns an instruction, not 100 | by design |
| `wfi` in user mode | QEMU makes it an illegal instruction, as the specification allows a hart with supervisor mode to | the specification allows either |
| A word loaded or stored at an odd address | QEMU makes the access itself, where DBT-RISE traps | the specification allows either |
| A page's accessed and dirty bits | QEMU sets them itself (Svadu), where DBT-RISE takes a page fault (Svade) | the specification allows either; Linux takes both |
| `satp`'s address-space identifier, Sv48 and Sv57 | QEMU has them; socpuppet's patch takes them out of DBT-RISE | either |
| `miselect` and `siselect` with no IMSIC | QEMU keeps them whenever it has the AIA's registers, which the qbox_cpu always asks for | the adapter's choice |
| A hart without supervisor mode | QBox's always has it | by design |
| Atomics to memory without direct access | Never complete: QEMU asks for the instruction to be run on its own and QBox's coroutine never does | ⚠️ QBox's to fix ([upstream.md](../upstream.md)) |
| An atomic at an odd address | QEMU raises a load's cause, where the specification says a store's | ⚠️ QEMU's to fix |
| A reset pulse while the CPU is busy and ahead of the clock | QBox does not take it | ⚠️ QBox's to fix |

## What it leaves out

- **A device's delay inside the quantum.** QBox keeps the CPU's time in QEMU's clock, which counts instructions, and forgets what a target adds to an access unless the CPU has to wait for SystemC there and then. ⚠️ At the boards' 100 µs a device that takes 3 µs costs this CPU nothing. Time a device against `dbt_rise_cpu` ([upstream.md](../upstream.md)).
- **Time while it traps on every fetch.** ⚠️ A CPU fetching from an address nothing answers, with `mtvec` at such an address too, executes nothing, so QEMU's instruction count stands still, the quantum never ends, and the simulation never comes back from it ([upstream.md](../upstream.md#qbox)). Load something where the CPU starts.
- **A no-quantum run that keeps time.** With no quantum, a CPU running from memory it reaches directly never waits for SystemC's clock, which then stands still while it runs. The boards set 100 µs. M26's 1 ms for 33.5 million instructions was that.
- **QEMU's threaded configuration**, a thread for each CPU with nothing to keep it in step. It hung in every environment M26 tried, and it would give up repeatability, which is the point of a second opinion.

## Where it comes from

💡 Borrowed. The CPU is QEMU's, through [QBox](https://github.com/qualcomm/qbox) at `4d63017c`, built by `tools/build_qbox.py` with the patches in `cmake/patches/qbox-*.patch` and `cmake/patches/libqemu-*.patch`. socpuppet's adapter is `src/socpuppet/models/qbox_cpu.cpp`: it funnels QBox's bus socket into its own, passes reset and the three interrupts on as they change, sets QBox's parameters before it is built, and answers the `time` register and the IMSIC's registers through hooks of QEMU's that a patch exports. Its one source file is the only one that sees QBox's headers.

What was changed, and why, is in [upstream.md](../upstream.md): three patches for C++20, four for what the contract and the suite found (a sleeping CPU that stopped time, the two hooks, and the reset handler's thread), one for what OpenSBI found (a parameter to switch Sstc off), and four so that it builds and runs on a Mac (QEMU without OpenGL, rpclib's own asio before Homebrew's, twice, and QEMU found from inside Python). CI builds it, when its pin or its patches change, and on every push runs all of the above on Linux and natively on an Apple silicon Mac and an Intel one, and twister's suites on the host board on the first two: the `qbox-build`, `qbox` and `qbox-tidy` jobs of `.github/workflows/ci.yml`, which `uv run python tools/ci.py qbox-build qbox qbox-tidy` runs here.
