# The GDB spike: a debugger on each CPU at once

This is the report of a spike for milestone M8 in [plan.md](plan.md), run on 2026-10-10. It ends with the decision that followed. 🦜 The spike's code has since been deleted, when M8's step 4 had rebuilt what it found test-first (`tests/python/test_gdb.py`). The last commit that holds `spikes/gdb/` is `c664738`, and the paths in this report are from there.

**In one paragraph.** DBT-RISE can give every CPU a GDB server of its own, on a port of its own, with a patch of about forty lines to its core library and three to its RISC-V library. Three debuggers then attach to the three CPUs of the host with all its firmwares, each finds its own CPU stopped where its firmware starts, each sets a breakpoint on its firmware's `main` and hits it, and the boot runs on to the disk test's verdict. The Zephyr SDK's GDB does the same as the spike's own client. ⚠️ A CPU stopped in its debugger stops the whole simulation, and the other two debuggers wait with it. That is kept, and the docs will say it. The spike also met a bug nobody was looking for: the server answered one `continue` twice, and the second answer ended the process if the debugger had hung up by then. That is patched too.

## The question

🎓 A GDB server is the part of a CPU model that a debugger talks to, over a TCP connection, in the remote serial protocol (RSP). socpuppet's CPU is DBT-RISE's, and so is its GDB server.

M3 gave one CPU a debugger. M6 put a second CPU in the simulation and found that DBT-RISE's server was one for the whole process: the second CPU to ask for a `gdb_port` ended the program, so the platform refuses it first. M8 has three CPUs and wants a debugger on each. Reading the code for M6's plan found three things in the way, all written up in [upstream.md](upstream.md) since then, and none of them tried.

So: can each CPU have its own server? And when one CPU is stopped at a breakpoint, what happens to the other two, and to their debuggers?

## What was tried

The platform is `host(manager=add_manager, drive=add_ssd)` with a `gdb_port` on all three CPUs: the host's 64-bit CPU running Zephyr's disk test, and the manager's and the SSD's 32-bit CPUs each running their own Zephyr application. The images are the ones M5 to M7 built. `spikes/gdb/three_debuggers.py` speaks RSP to the three servers from three threads, and `spikes/gdb/real_gdb.sh` does the same with three of the Zephyr SDK's GDBs.

DBT-RISE was changed in place, in the build tree's checkouts, until the experiments passed. The changes were then cut into patch files against the pinned commits, and the build was made to apply them to clean checkouts, which gave back byte for byte what had been developed.

## Answers

| Question | Answer |
|---|---|
| Can each CPU have its own GDB server? | ✅ Each server already had its own thread, socket and queue of work. What stopped a second was a static pointer and a check. |
| Does each debugger reach its own CPU? | ✅ The host's is stopped at 0x8000_0000 and the other two at 0x2000_0000. The two 32-bit images start with the same Zephyr code, so the experiment reads 2 KiB of each back through its debugger and compares it with what was loaded: each debugger has its own. |
| Is each sent the right description of its CPU? | ✅ `riscv:rv64` to the host's and `riscv:rv32` to the other two, once the description stopped being a static shared by every session. |
| Does `monitor sysc print_time` go to the right core? | ✅ Each core now adds the command to its own server. The manager's and the SSD's say `0 s` and the host's says `5500 us`, which is when the link lets it go. |
| Do breakpoints work on all three? | ✅ `main` is hit at 1.4 ms in the manager, 3.3 ms in the SSD and 142.7 ms in the host, each reported once. |
| Does the boot survive being debugged? | ✅ The verdict is `PROJECT EXECUTION SUCCESSFUL` at 603.7 ms of simulated time in every experiment, which is when it comes with no debugger at all. |
| Does a real GDB agree? | ✅ Three of the Zephyr SDK's (1.0.1) at once, each with its firmware's symbols: attach, `break main`, `continue`, `backtrace`, `continue`. |
| What do the others do while one CPU is stopped? | They wait. See below. |

## A stopped CPU stops the world

SystemC runs every process of a simulation on one thread. A DBT-RISE core that is stopped in its debugger does not give that thread back: it stays in a loop, doing whatever its own debugger asks, until the debugger says continue. So nothing else in the simulation moves, and simulated time stands still.

A debugger's questions about memory are handed to that loop, each server's to its own core's. So a debugger gets no answer about memory until its own CPU is the one that is stopped. In the `frozen` experiment the manager's CPU was the first to stop, and its debugger held it for two seconds of wall clock. The SSD's debugger and the host's had both asked for a byte of memory by then. The SSD's was answered a millisecond after the manager's said continue, and the host's five milliseconds after that.

What this means for somebody with three GDB windows:

- **Any order of attaching works, if GDB is told to be patient.** GDB reads memory as it attaches, and gives up after two seconds unless told otherwise. `set remotetimeout 60` before `target remote` is what the spike's script does, and with it the three were started at once.
- **Each CPU must be told to continue once.** The manager's and the SSD's stop at time 0. The host's is held in reset by the link, so it stops at 5.5 ms, which it cannot reach until the other two are running.
- **While one CPU is at a breakpoint, the other two are frozen with it**, at whatever instruction they had reached. That is what makes a three-CPU debugging session repeatable: nothing runs on behind your back. It also means the other two GDBs cannot look at memory until the stopped one continues.
- ⚠️ **Leave with `continue`, not `detach`.** A debugger that detaches leaves its CPU stopped, and the simulation with it, for ever. A second debugger can attach to the same port and say continue, which the `detach` experiment does.

**The other design**, which was not built: let whichever core is stopped serve every debugger's questions, so that the SSD's memory can be read while the host sits at a breakpoint. It is possible, because everything would still happen on the simulation's thread. It would need a registry of servers in DBT-RISE-Core, so that the stopped core can look in every server's queue and not only its own. It would need another way for a single step to know that its core has stopped again, which today is a flag that only the waiting loop sets. And it would need an answer for stepping a core that is not the one holding the thread, which cannot run while another core holds it. It is a to-do for after M8, if the walkthrough shows people want it.

## What surprised

- **One `continue` was answered twice.** The server handed the debugger's "tell me when it stops" to the core, and then also waited a second itself and answered: `OK` if the core was still running, which is not a reply RSP has for `continue`, and a second `S05` if it had stopped. So a breakpoint hit within a second was reported twice, and the debugger's next question was answered with the second report. The spike's client read `S05` where it had asked for the program counter.
- **A debugger that hung up within a second of `continue` ended the process.** The late answer was written to a closed socket. The failure was logged as an error, and SCC turns an error that is logged into a C++ exception, here on the server's thread, where nothing catches it. Every GDB test in the tree does exactly this, continue and hang up, and passes only because its run is over in less than a second. M8's tests run for longer. One patch, `dbt-rise-core-gdb-continue-answered-once.patch`, fixes both: a `continue` is answered by the stop, once.
- ⚠️ **A debugger that hangs up rudely still ends the process**: one whose connection is reset, or that closes with an answer unread. This is not patched. It is in [upstream.md](upstream.md).
- **The server sends at most 184 bytes of memory for one request**, however many were asked for. RSP allows a short answer, and GDB asks again for the rest. A test client has to do the same.
- **The three-firmware boot itself just works.** `iomgr_socpuppet_iomgr.elf` was built for the IO manager board and had never run under the host. It trains the link and lets the host go, and the disk test passes against the SSD's firmware, with no image rebuilt. On the machine the spike ran on (an Intel Mac) that boot takes 0.46 s of wall clock with no debugger.

## Cost

| | |
|---|---|
| `dbt-rise-core-gdb-server-per-core.patch` | 3 files. `run_server` starts one more server each time it is called and returns it. `get(vm)` finds the server started for a core. The target description is a member of the session. |
| `dbt-rise-riscv-gdb-server-per-core.patch` | 1 file, 3 lines. A core asks for its own server before it adds its `sysc` command. |
| `dbt-rise-core-gdb-continue-answered-once.patch` | 2 files, 12 lines. A core that runs on is answered by its stop callback and by nothing else. |
| socpuppet's own code | none in the spike. `spikes/gdb/a-port-each.patch` took the refusal out of `dbt_rise_cpu.cpp` for the experiments, and was not applied in the tree. |

With the three patches in and the refusal still there, all 624 tests pass, with the firmware images required.

## Not exercised

- Linux. The spike ran on macOS, with GDB in the devcontainer's image, since the SDK has no GDB for an Intel Mac. CI will run M8's tests on both.
- Single-stepping, watchpoints, and writing registers or memory from a debugger, on more than one CPU.
- Interrupting a running CPU from its debugger (Ctrl-C) while another is stopped. By reading: the debugger is told its CPU has stopped at once, and its questions about memory are answered when the CPU really has.
- A debugger that attaches after the boot has started. [boot-your-firmware.md](boot-your-firmware.md) has the run started first for one CPU, and three are no different, but it was not tried.

## Decisions

Decided on 2026-10-10, planning M8:

- **Each CPU that asks gets its own GDB server**, by the three patches above. The platform's refusal of a second `gdb_port` went in M8's step 4, test-first, and the spike with it.
- **A stopped CPU stops the world, and that is the design.** One queue of work a server, as upstream has it. The docs say what it means for the order of things, and the walkthrough is written around it.
- **`set remotetimeout` is part of the recipe** for more than one GDB.
- **Things M8's step 4 needs to know**: a breakpoint test can be fast and exact (set it, continue, read the stop reply, ask for the program counter, which before the patch came back as `S05`). A test that hangs up after `continue` and runs on for more than a second of wall clock holds the other half of that patch. The test client's `read_memory` has to ask again after a short answer. And a test with a CPU nobody tells to continue never ends, whatever its limit in simulated time: give every debugger thread a `finally` that says continue, as `run_with_a_debugger` does.
