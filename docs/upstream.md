# 📮 What we owe upstream

socpuppet borrows before it builds: the router, the CPU and the peripherals come from other open-source projects. Sometimes a borrowed piece needs a fix or an accommodation before it works here. Each one is written down on this page, with enough context to open an issue or a pull request from it later.

🚧 Nothing on this page has been sent yet. This is the list to work from when it is.

## How to use this page

**Adding an entry.** A change to someone else's code is a `git apply` file in `cmake/patches/`. The commit that adds the patch also adds its entry here, so the page never lags the patches. A limitation we work around without a patch gets an entry too.

Each entry says:

- **Where**: the file, in the project and at the commit we pin.
- **What is wrong**: in a sentence a maintainer can act on.
- **How to see it**: the compiler or the test that shows it.
- **What we do**: our patch or workaround, and where it lives.
- **Upstream fix**: what to propose, where that differs from our patch.
- **Kind**: bug, portability, build, or missing feature.
- **When it lands**: what socpuppet can delete.

**Before sending one.** ⚠️ Look at the project's current head first. The commits pinned here are a snapshot, and the fix may already be there. The "how to see it" lines are as recorded when each patch was made, so run them again against the head before quoting them.

## SystemC-Components (SCC)

[Minres/SystemC-Components](https://github.com/Minres/SystemC-Components), pinned at `42a9843e` ("2026.07") in `cmake/Dependencies.cmake`. socpuppet uses its TLM router and its logging.

### The stage-callback probe cannot see a SystemC built in the same tree

- **Where**: `src/sysc/CMakeLists.txt`, the `try_compile` that decides `HAVE_STAGE_CALLBACKS`.
- **What is wrong**: the probe passes `LINK_LIBRARIES SystemC::systemc`. 🎓 `try_compile` configures a small separate project, and a target that the enclosing build is about to compile does not exist there. So when SystemC comes from `FetchContent` or `add_subdirectory`, and not from an installed package, the probe cannot succeed.
- **How to see it**: fetch SystemC 3.0.2 and SCC with `FetchContent` in one project and configure. The probe only compiles a source file to a static library, so it never needed to link.
- **What we do**: `cmake/patches/scc-in-tree-systemc.patch` replaces the `LINK_LIBRARIES` line with `CMAKE_FLAGS "-DINCLUDE_DIRECTORIES=${systemc_SOURCE_DIR}/src"`.
- **Upstream fix**: our patch names the fetched source directory, which is too specific to send as it is. Propose giving the probe SystemC's include directories instead of linking the target, read from the target's properties, so that both an installed and an in-tree SystemC work.
- **Kind**: build.
- **When it lands**: delete the patch file and its line in `PATCH_COMMAND`.

### `Boost::filesystem` is used but not linked

- **Where**: `src/sysc/CMakeLists.txt`. It calls `find_package(Boost ... COMPONENTS date_time filesystem)` and then links only `Boost::date_time`. Four sources under `src/sysc/scc/scv/` include `<boost/filesystem.hpp>` (`scv_tr_mtc.cpp`, `scv_tr_lz4.cpp`, `scv_tr_binary.cpp`, `scv_tr_ftr.cpp`).
- **What is wrong**: with a system-wide Boost every header sits in one include directory, so the missing link goes unnoticed. With a Boost that has one target per library (Boost's own CMake build, which is what `FetchContent` gives), the header is not on the include path.
- **How to see it**: build SCC against Boost 1.89.0 fetched with `FetchContent` and `BOOST_INCLUDE_LIBRARIES date_time filesystem`.
- **What we do**: `target_link_libraries(scc-sysc PUBLIC Boost::filesystem)` in `cmake/Dependencies.cmake`, after SCC is added.
- **Upstream fix**: the same line, in SCC's own `CMakeLists.txt`.
- **Kind**: build.
- **When it lands**: delete that line and its comment.

### An in-tree SystemC has to be declared "found" by hand

- **Where**: SCC's top-level `CMakeLists.txt`, which looks for an installed SystemC through its `SystemCPackage` module, and `src/sysc/CMakeLists.txt`, which stops with "No usable SystemC installation found" when `SystemC_FOUND` is not set.
- **What is wrong**: a project that already has a `SystemC::systemc` target, because it builds SystemC itself, has no supported way to say so.
- **How to see it**: add SCC to a project that builds SystemC from source, without setting anything.
- **What we do**: `set(SystemC_FOUND TRUE)` and `set(SystemC_LIBRARIES SystemC::systemc)` before SCC is added, in `cmake/Dependencies.cmake`.
- **Upstream fix**: skip the search when the target already exists (`if(TARGET SystemC::systemc)`), and treat that as found.
- **Kind**: build.
- **When it lands**: delete the two `set` lines and their comment.

### Install rules cannot be switched off

- **Where**: SCC's `install(TARGETS ... EXPORT ...)` rules.
- **What is wrong**: an export set requires every target it depends on to be installable as well. A project that links SCC statically into its own binary and never installs it still has to satisfy that, for SystemC, Boost and the rest.
- **How to see it**: add SCC with `FetchContent` next to dependencies that have no install rules of their own, and configure.
- **What we do**: `cmake/Dependencies.cmake` overrides CMake's `install()` with a function that does nothing while SCC is being added. It works, and it is the kind of thing nobody should have to write.
- **Upstream fix**: an option, off for a top-level build and on when SCC is a subproject, that skips the install rules. `BUILD_SCC_LIB_ONLY` is the natural neighbor for it.
- **Kind**: build, missing feature.
- **When it lands**: delete the `install` override and the `SOCPUPPET_SUPPRESS_INSTALL` lines around SCC. DBT-RISE is added under the same override, so check that first.

### LWTR4SC's `record` is ambiguous for `unsigned long` with Clang

- **Where**: `third_party/lwtr4sc/src/lwtr/lwtr.h` line 98, reached from `third_party/axi_chi/chi/lwtr/chi_lwtr.cpp` line 25. LWTR4SC is [Minres/LWTR4SC](https://github.com/Minres/LWTR4SC), bundled with SCC.
- **What is wrong**: recording a field of type `unsigned long` fails with "call to 'record' is ambiguous". On macOS `uint64_t` is `unsigned long long`, so `unsigned long` is a different type with no overload of its own.
- **How to see it**: build SCC's `tlm-interfaces` target (its AXI and CHI library) with Apple clang 21 as C++20. socpuppet met it by accident, when a dependency linked all of SCC. It was not looked into further.
- **What we do**: nothing. socpuppet does not build that library.
- **Upstream fix**: an overload or a conversion for `unsigned long`.
- **Kind**: portability.
- **When it lands**: nothing to delete here.

### A debug access is all or nothing, and what it does depends on the kind of register

- **Where**: `src/components/scc/tlm_target.h`, `tranport_dbg_cb`; `src/components/scc/register.h`, `sc_register::read_dbg` and `write_dbg`; and `src/components/scc/tlm_target_bfs_register_base.h`, `bitfield_register::read_dbg` and `write_dbg`.
- **What is wrong**: 🎓 a debug access is a debugger's look at a register: no simulated time, no side effects. Three things get in its way here.
  - `tranport_dbg_cb` declines an access that is not exactly as wide as the register, where an ordinary access may be narrower. A debugger that reads one byte of a four-byte register gets nothing.
  - An `sc_register` answers a debug access by doing the ordinary read or write, callbacks and all, unless its CCI parameter `<name>.enableSideEffect` is turned off. It is on by default. So a debug read of the PLIC's claim register claims the interrupt.
  - A `bitfield_register` does the opposite, with no parameter: a debug access reads and writes the stored word and skips the bit fields and their callbacks. So a debug read of a register that a callback computes, like the UART's line status, shows a stale word, and a debug write lands where an ordinary read does not look.
- **How to see it**: `InterruptControllerContract.ADebugAccessToTheClaimRegisterDoesNotClaim` in `tests/cpp/contracts/interrupt_controller_contract.h` with the PLIC adapter forwarding every debug access, and `UartContract.TheScratchRegisterIsSeenByADebugAccess` in `tests/cpp/contracts/uart_contract.h` with the UART adapter forwarding a one-byte debug read as it is.
- **What we do**: no patch. The PLIC adapter declines a debug access to the claim register. The UART adapter fetches the whole four-byte register and hands back its low byte, and declines a debug write.
- **Upstream fix**: let a debug access be narrower than the register, as an ordinary one may be. Make side effects off the default for a debug access, and give `bitfield_register` the same choice, with a read callback told that the access is a debug one so that a computed register can answer without acting.
- **Kind**: limitation.
- **When it lands**: both adapters can forward every debug access.

### SCC's SPI sockets are in a library that does not compile here

- **Where**: `src/interfaces/CMakeLists.txt`, the `interfaces` library (`scc::busses`), which has `spi/spi_tlm.h` beside AHB, AXI and CHI, and `third_party/axi_chi/chi/lwtr/chi_lwtr.cpp`.
- **What is wrong**: the SPI sockets are headers, and the only target that puts them on an include path is the whole `interfaces` library. Linking it compiles the AXI and CHI transaction recorders, and with Apple's Clang `chi_lwtr.cpp` fails: a call to `record` is ambiguous between three templates.
- **How to see it**: link `scc::busses` into anything, on a Mac.
- **What we do**: `src/socpuppet/CMakeLists.txt` adds `${scc_SOURCE_DIR}/src/interfaces` to the flash model's include path and links nothing new.
- **Upstream fix**: an interface target for the header-only protocols, and the ambiguity in `chi_lwtr.cpp` mended, which is the same one as in "LWTR4SC's `record` is ambiguous" above.
- **Kind**: build.
- **When it lands**: link the target, and drop the include path.

## SystemC CCI

[accellera-official/cci](https://github.com/accellera-official/cci). socpuppet gets it as the copy SCC bundles in `third_party/cci-1.0.1`, so the fix belongs to Accellera, and SCC would pick it up from there.

### Two protected constructors that should be `explicit`

- **Where**: `cci/core/cci_value.h`, the constructors `cci_value_map_elem_cref(impl_type i = NULL)` and `cci_value_map_elem_ref(impl_type i = NULL)`, where `impl_type` is `void*`.
- **What is wrong**: the constructors are protected and not `explicit`, so each is an implicit conversion from `void*`. CCI's map iterators give `void*` as their value type and return the element reference by value. When `std::reverse_iterator` classifies such an iterator, GCC 13's standard library asks for the common reference of the two types and finds that conversion. GCC takes the access failure for a "no". Clang reports it as an error.
- **How to see it**: run clang-tidy (22.1.8 here) on any file that includes CCI, with compile commands from GCC 13 on Ubuntu 24.04. It stops in the CCI header, and what it says about the including file afterwards is noise. The commit message of `7285dfd` has the full account.
- **What we do**: `cmake/patches/scc-cci-explicit-elem-ref.patch` adds `explicit` to both. CCI only ever calls them directly, so nothing else changes.
- **Upstream fix**: the same two words, to Accellera's repository. Mention it to SCC as well, since they ship the copy.
- **Kind**: portability.
- **When it lands**: delete the patch file and its line in `PATCH_COMMAND`, once SCC's bundled copy has it.

## DBT-RISE-Core

[Minres/DBT-RISE-Core](https://github.com/Minres/DBT-RISE-Core), pinned at `29e97c0`. It is the engine under the CPU model. How each of these was found is in [iss-spike.md](iss-spike.md), and for its GDB server in [gdb-spike.md](gdb-spike.md).

### asio names that Boost 1.87 removed

- **Where**: `src/iss/debugger/serialized_connection.h` and `src/iss/debugger/server.h`.
- **What is wrong**: the GDB server uses `boost::asio::io_service` and `boost::asio::io_context::work`. Boost 1.87 removed both names.
- **How to see it**: compile against Boost 1.87 or newer. Ours is 1.89.0. It fails on every platform.
- **What we do**: `cmake/patches/dbt-rise-core-asio-names.patch`, three edits. `io_service&` becomes `io_context&` in the connection's constructor. The `work` object becomes an `executor_work_guard<io_context::executor_type>`, constructed from `io_service.get_executor()`.
- **Upstream fix**: the same. The new names have existed since Boost 1.66, so no version check is needed.
- **Kind**: portability.
- **When it lands**: drop the patch.

### 128-bit integer traits that only GCC's standard library accepts

- **Where**: `src/iss/interp/vm_base.h`, the block after `using uint128_t = unsigned __int128;` that opens `namespace std`.
- **What is wrong**: it specializes `std::__make_unsigned_selector`, which is a private template of GCC's standard library, along with `is_signed` and `is_unsigned`. Clang's library has no such template, forbids specializing these traits, and already knows the 128-bit types.
- **How to see it**: compile with Apple clang or with Clang and libc++.
- **What we do**: `cmake/patches/dbt-rise-core-int128-traits.patch` wraps the block in `#ifdef __GLIBCXX__`.
- **Upstream fix**: the same guard.
- **Kind**: portability.
- **When it lands**: drop the patch.

### A function called `wait()` collides with POSIX on macOS

- **Where**: `src/iss/vm_jit_funcs.h` line 13 and `src/iss/vm_jit_funcs.cpp` line 79: `extern void wait(void*, uint64_t);`
- **What is wrong**: it is a C-linkage helper for the translating backends, and POSIX already declares `wait()`. On macOS the two declarations meet and the file does not compile.
- **How to see it**: build DBT-RISE-Core on macOS.
- **What we do**: no patch. No translating backend is built, so `cmake/Dependencies.cmake` removes the file from the target's sources. A backend would need it back, which is why this blocks the "try the other backends" to-do on macOS.
- **Upstream fix**: rename the helper, for example to `iss_wait`, along with the other helpers in that file that the generated code calls.
- **Kind**: portability.
- **When it lands**: stop removing the file.

### Boost headers are assumed to share one include directory

- **Where**: the `CMakeLists.txt` of DBT-RISE-Core and of DBT-RISE-RISCV.
- **What is wrong**: they include headers from about fifteen Boost libraries and link only a few of them. As with SCC above, that works with a system-wide Boost and not with one target per library.
- **How to see it**: build against a Boost fetched with `FetchContent`.
- **What we do**: `cmake/Dependencies.cmake` links the list by hand onto `dbt-rise-core` and `dbt-rise-riscv`: asio, bind, coroutine2, foreach, fusion, lexical_cast, optional, phoenix, serialization, smart_ptr, spirit, thread, tokenizer, tuple, variant.
- **Upstream fix**: link each library whose headers are included.
- **Kind**: build.
- **When it lands**: delete the list.

### One GDB server per process

- **Where**: three places in `src/iss/debugger/`. `server.h`, `server<SESSION>::run_server`, lines 50 to 56. `cmdhandler.h`, line 92, where a session takes its target: `s.get_target(0) // FIXME: add core id`. `cmdhandler.cpp`, line 583, in the answer to `qXfer:features:read`: `static std::string buf`.
- **What is wrong**: the server is a singleton. A second call logs "server already initialized" as fatal. So only one CPU in a process can have a debugger attached, whatever port each asks for. A platform with three CPUs and three firmware images wants three. And the target description a debugger asks for is read from the target once and kept in a static that every session shares, so with more than one server the second debugger to attach is sent the first one's: a 32-bit core described as the 64-bit one, or the other way about.
- **How to see it**: two `core_complex` instances in one simulation, each with a `gdb_server_port`. The static was found by reading, when M6 was planned, and was taken out before it could be run into. With the patch, a debugger on an RV64 core and one on an RV32 core that each ask for `qXfer:features:read:target.xml` are told `riscv:rv64` and `riscv:rv32`.
- **What we do**: `cmake/patches/dbt-rise-core-gdb-server-per-core.patch`. `run_server` starts one more server each time it is called, and returns it. The servers are kept in a list, `get()` is the first of them, as it was, and `get(vm)` is the one started for a core. The target description is a member of the session's command handler. A session still takes target 0 of its server, which is right now that a server has one core. `tests/python/test_gdb.py` holds it: two CPUs with a port each, and the host's three, each debugger finding its own CPU.
- **Upstream fix**: the same, or one step further: let `run_server`'s caller own what it returns, and drop the list.
- **Kind**: missing feature.
- **When it lands**: drop the patch. ⚠️ A CPU stopped in a debugger keeps the simulation's one thread, in `server_if.h`'s `check_continue`, so every other CPU stops with it, and a debugger's question about memory is answered only while its own CPU is the one stopped. That is what makes debugging several of them repeatable. It is ours to design around and to document, not upstream's to fix.

### One `continue` is answered twice

- **Where**: `src/iss/debugger/cmdhandler.cpp`, `cmd_handler::running`, from "Now we have to wait for the target" to the end, and `src/iss/debugger/gdb_session.cpp`, the `case 'c'` of `parse_n_execute`, which calls it with `blocking` false.
- **What is wrong**: for a `continue`, `running` hands the session's stop callback to the core, which sends the stop reply when the core stops. It then also calls `wait_non_blocking`, which sleeps for a second, and answers the packet itself: `S05` if the core has stopped by then, and `OK` if it has not. So a core that stops within a second is reported twice, and a core that runs on is answered with `OK`, which is not a reply the protocol has for `continue`. A debugger that takes the first `S05` and asks its next question reads the second `S05` as the answer. ⚠️ And a debugger that hangs up within a second of saying `continue` ends the process: the late answer is written to a closed socket, the failure is logged with `CLOG(ERR, ...)`, and SCC turns a logged error into a thrown `sc_report`, on the server's thread, where nothing catches it.
- **How to see it**: attach, set a breakpoint a few instructions on, send `c`, read the `S05`, send `p20`: the answer is `S05`. For the other half: attach, send `c`, close the socket, and keep the process alive for two seconds. It ends with "terminating due to uncaught exception of type sc_core::sc_report: Error: gdbconn: Communication error". Every test in `tests/python/test_gdb.py` says continue and hangs up, and until M8 each passed because its process was gone within the second.
- **What we do**: `cmake/patches/dbt-rise-core-gdb-continue-answered-once.patch`. `running` returns nothing for a resume that was given a stop callback, and the session sends nothing when it is given nothing, so the callback's is the only reply. A single step is answered as before: it has no callback and has finished by the time it is answered. Two tests in `tests/python/test_gdb.py` fail without it: `TestWhenACpuReachesABreakpoint` and `TestWhenADebuggerSaysContinueAndHangsUp`.
- **Upstream fix**: the same. `handle_extended` already treats an empty answer from `running` as "nothing to send yet", so this looks like what was meant.
- **Kind**: bug.
- **When it lands**: drop the patch.

### A debugger that hangs up rudely ends the process

- **Where**: `src/iss/debugger/gdb_session.cpp`: `receive_completed`, "Communication error", and the two `catch` blocks at the end of `parse_n_execute`. All three log with `CLOG(ERR, connection)`. And `src/iss/debugger/serialized_connection.h`, `async_read_data`, whose catch-all turns anything thrown while a packet is handled into a call of `receive_completed` with `invalid_argument`.
- **What is wrong**: an error on a debugger's connection is logged as an error, and under SCC's reporting a logged error is thrown as an `sc_report`. These run on the server's own thread, where nothing catches it, so the process ends. A debugger that closes its connection cleanly is the one case handled apart, as a warning. One whose connection is reset is not, nor is one that closes with an answer unread, which resets it. The catch-all was written for data that cannot be decoded, and it also takes a handler's failure and gives it a new name: an answer that could not be written, or the `sc_report` thrown by one of the two `catch` blocks, comes back as "Invalid argument".
- **How to see it**: attach, send `c`, set `SO_LINGER` to zero on the socket and close it. Or attach, send any packet, wait for the server's `+` to arrive, and close without reading it. The process ends with "Communication error (Connection reset by peer)" when it is a read that fails, and "(Invalid argument)" when it is an answer that could not be written. Both were tried by hand in [the GDB spike](gdb-spike.md), with one CPU. ⚠️ The second needs no rude debugger at all. Every test in `tests/python/test_gdb.py` says `continue` and hangs up, and whether the `+` for that `continue` has arrived by then is a race. On a busy machine the tests lost it: CI failed on 2026-10-11 with a different handful of them aborted in each job.
- **What we do**: `cmake/patches/dbt-rise-core-gdb-rude-hangup.patch`, one word: the error in `receive_completed` is logged as a warning, and the session is dropped as it was. Because of the catch-all, that one word covers the two `catch` blocks as well: what they throw lands in the same branch. `TestWhenADebuggerHangsUpWithAnAnswerUnread` in `tests/python/test_gdb.py` holds the read that fails, by waiting for the `+` before it closes. The answer that cannot be written was tried by hand with the patch (attach before the run, send `m0,1`, close with the `+` unread, run): a warning, and the run goes on. No test holds that one.
- **Upstream fix**: log a connection's failures as warnings and drop the session, as is done for a clean close. And narrow the catch-all in `async_read_data` to the decoding it was written for, so that a handler's failure keeps its own name.
- **Kind**: bug.
- **When it lands**: drop the patch.

### A GDB port that cannot be had ends the build with no word of which

- **Where**: `src/iss/debugger/server.h`, the constructor of `server<SESSION>`, which makes its `acceptor` on the port it was given. It is reached from `core_complex::before_end_of_elaboration`.
- **What is wrong**: if the port is taken, the acceptor's constructor throws Boost's own error, "bind: Address already in use", with a file and a line of Boost's and neither the core's name nor the port's number. Under SystemC that is the end of elaboration, and the kernel cannot be started again in the same process.
- **How to see it**: two cores given the same `gdb_server_port`, or one given a port another program is listening on, such as an earlier run that is still there.
- **What we do**: half of it. A platform refuses a description in which two CPUs have the same `gdb_port`, before the simulator is created, and names both and the port (`_refuse_a_shared_gdb_port` in `python/socpuppet/platform.py`, held by `TestWhenTwoCpusAreGivenTheSameGdbPort`). ⚠️ A port that something outside the simulation holds still ends the build with Boost's words.
- **Upstream fix**: catch the error where the server is started and say which core wanted which port.
- **Kind**: missing feature.
- **When it lands**: nothing to delete. The check on a description is worth having either way, since it comes before the simulator exists.

### A debugger that detaches leaves its CPU stopped

- **Where**: `src/iss/debugger/cmdhandler.cpp`, `cmd_handler::detach`.
- **What is wrong**: the answer to `D` is sent and nothing else is done. A core that was stopped stays stopped, with no debugger to tell it to go on. GDB sends `D` when it is told to `detach`, and when it quits, because the server answers `qAttached` with 1: quitting the SDK's GDB at a stopped CPU says "Inferior 1 [Remote target] will be detached" and leaves the simulation where it was. Under SystemC a stopped core holds the simulation's one thread, so the whole simulation stays where it is, and no limit in simulated time ends the run.
- **How to see it**: attach, send `D`, hang up. The simulation makes no progress. A second debugger that attaches to the same port and sends `c` sets it going again, which the `detach` experiment of [the GDB spike](gdb-spike.md) did.
- **What we do**: nothing in code. [boot-your-firmware.md](boot-your-firmware.md) says to leave with `continue`, and what to do if it is too late for that.
- **Upstream fix**: resume the core on `D`, and when a session's connection closes, as `gdbserver` does for a process it was attached to. Clear the adapter's break condition then as well as its breakpoints. `target_adapter_base::close` clears only `bp_lut`, so a `monitor sysc break <time>` left by a debugger that has gone still stops the core later, and the stop reply, written to a closed connection, ends the simulation with "write: Broken pipe".
- **Kind**: bug, or at least a surprise.
- **When it lands**: the warning can come out of the docs.

## DBT-RISE-RISCV

[Minres/DBT-RISE-RISCV](https://github.com/Minres/DBT-RISE-RISCV), pinned at `2ad3223`. It is the default CPU, wrapped by `src/socpuppet/models/dbt_rise_cpu.cpp`.

### `offsetof` with a qualified member name

- **Where**: the generated register tables in `src/iss/arch/*.h`, nine headers. They come from the template `gen_input/templates/CORENAME.h.gtl`, lines 198 to 202.
- **What is wrong**: the tables say `offsetof(core::regs, core::regs::X0)`. GCC accepts a qualified member name there and Clang does not.
- **How to see it**: compile with Clang on any platform.
- **What we do**: `cmake/patches/dbt-rise-riscv-offsetof.patch` drops the qualification in all nine headers: `offsetof(core::regs, X0)`. About 600 changed lines, all from one rule: the regular expression `offsetof\(([a-z0-9_]+::[A-Za-z0-9_]+), [a-z0-9_]+::[A-Za-z0-9_]+::` replaced by `offsetof(\1,`.
- **Upstream fix**: change the template, then regenerate the headers. Patching the headers alone would be undone by the next generation.
- **Kind**: portability.
- **When it lands**: drop the patch.

### Raising reset a second time stops the simulation

- **Where**: `src/sysc/core_complex.cpp`, the SystemC wrapper.
- **What is wrong**: reset held high from the start and then released works. Raised again later, three things go wrong.
  1. The run loop ends on any interruption and then stops the whole simulation, and a reset counts as an interruption.
  2. A core asleep in `wfi` wakes only for an interrupt, so it does not notice reset at all.
  3. Reset sets the core's cycle count back to zero, but `last_sync_cycle`, which the quantum keeper measures progress from, keeps its old value. The difference comes out as an enormous number of cycles, and the core waits that long before its first instruction.
- **How to see it**: a platform that raises `rst_i` on a running core. In socpuppet that is `BusMasterContract.WhenResetIsRaisedAgainTheMasterStartsOver` in `tests/cpp/contracts/bus_master_contract.h`, run for the CPU with the patch taken out.
- **What we do**: `cmake/patches/dbt-rise-riscv-reset-restart.patch`, three edits. The loop condition becomes `while(!core->get_interrupt_execution() || rst_i.read())`. The reset callback also calls `vm->get_arch()->cancel_wait()`. And `last_sync_cycle` is set from the core's cycle count next to `quantum_keeper.reset(...)`.
- **Upstream fix**: the same three edits, sent as one change with the scenario above as the test.
- **Kind**: bug.
- **When it lands**: drop the patch.

### A reset shorter than a busy core's lead stops the simulation

- **Where**: `src/sysc/core_complex.cpp`, the reset callback and the run loop.
- **What is wrong**: a core that is executing runs ahead of the simulation's clock and looks at its inputs when it next waits, which with a quantum of 100 µs is up to 100 µs later. `rst_cb`, a method, sees reset rise and interrupts the core. If the line has fallen again by the time the core's thread wakes, the loop condition `!core->get_interrupt_execution() || rst_i.read()` is false, the loop ends, and `sc_stop()` ends the simulation. 🎓 A reset is a pulse a few clock ticks long, which is far shorter than a quantum, so this is what any reset from a watchdog or a reset controller does to a busy core. A core asleep in `wfi` is woken at once and is not caught.
- **How to see it**: raise `rst_i` for 1 µs on a core that is spinning, with a quantum of 100 µs. In socpuppet that is `WhenAResetPulseComesAndGoesWhileABusyCpuIsAheadOfTheClock` in `tests/cpp/platform/cpu_test.cpp`, and with a watchdog's line and a system controller between, `WhenTheWatchdogBitesACpu` in `tests/cpp/platform/system_controller_test.cpp`, each run with the patch taken out.
- **What we do**: `cmake/patches/dbt-rise-riscv-reset-pulse.patch`. The callback notes that reset has risen (`reset_seen`). The thread restarts the core when either the line is high or one was noted, waits for the line to fall only if it is still high, and the loop goes round again while one is noted.
- **Upstream fix**: the patch as it is, with the scenario above as the test. It builds on the reset-restart change above.
- **Kind**: bug.
- **When it lands**: drop the patch.

### The library is `SHARED` whatever the build asks for

- **Where**: `CMakeLists.txt` line 175, `add_library(${PROJECT_NAME} SHARED ${LIB_SOURCES})`, and line 187, `target_force_link_libraries(${PROJECT_NAME} PRIVATE dbt-rise-core)`.
- **What is wrong**: `BUILD_SHARED_LIBS=OFF` has no effect, so a project that links everything statically cannot. 🎓 socpuppet has to: one binary must hold the one SystemC kernel, and the Python wheel ships a single extension module with nothing beside it. The second line pulls all of the core library into the shared one with raw linker flags, which mean nothing for a static library.
- **How to see it**: configure with `-DBUILD_SHARED_LIBS=OFF` and look at what is built.
- **What we do**: `cmake/patches/dbt-rise-riscv-static-library.patch`. When `BUILD_SHARED_LIBS` is set and off, the library is `STATIC` and links `dbt-rise-core` in the ordinary way. When it is on or not set at all, nothing changes.
- **Upstream fix**: the patch as it is. It keeps their default.
- **Kind**: build.
- **When it lands**: drop the patch.

### Cores register themselves from a static initializer

- **Where**: `src/sysc/register_cores.cpp`, in the `dbt-rise-riscv_sc_sig` and `dbt-rise-riscv_sc_tlm` libraries.
- **What is wrong**: each core type adds itself to a factory from a static initializer that no other code refers to. As a static library, a linker that takes only what is needed leaves that object file out, and `core_complex` then fails with "Could not create core" for every type.
- **How to see it**: link `dbt-rise-riscv_sc_sig` as an ordinary static library and construct a `core_complex`.
- **What we do**: no patch. `src/socpuppet/CMakeLists.txt` links the whole archive: `$<LINK_LIBRARY:WHOLE_ARCHIVE,dbt-rise-riscv_sc_sig>`.
- **Upstream fix**: a function to call, such as `sysc::riscv::register_cores()`, next to or in place of the static initializer. Or make the library an `OBJECT` library.
- **Kind**: build.
- **When it lands**: link the library in the ordinary way.

### A withdrawn DMI grant is ignored unless it names one region exactly

- **Where**: `src/sysc/core_complex.cpp`, the two `register_invalidate_direct_mem_ptr` callbacks in `init`.
- **What is wrong**: 🎓 a memory that has granted direct access (DMI) can take it back, for a range of addresses. The callbacks look up the granted region that holds the range's start address, and drop it only if the range also ends inside that region. A range wider than the region, such as the common "everything" (`0` to the largest address), drops nothing. The core then keeps reading and writing through a pointer it was told to forget.
- **How to see it**: grant a core DMI to a memory, let it run, then call `invalidate_direct_mem_ptr(0, UINT64_MAX)` and refuse further grants. The core makes no more bus transactions. In socpuppet that is `WhenAMemoryWithdrawsDirectAccess.TheCpuGoesBackToTheBus` in `tests/cpp/platform/cpu_test.cpp`, with the patch taken out.
- **What we do**: `cmake/patches/dbt-rise-riscv-dmi-invalidate.patch`. A range that fits inside the region holding its start drops that region, as before. Any other range clears the whole table, and each region is asked for again when it is next needed.
- **Upstream fix**: the patch is correct and blunt. Dropping exactly the regions that overlap the range would keep more grants alive, and needs a way to walk `util::range_lut`, which it does not have today.
- **Kind**: bug.
- **When it lands**: drop the patch.

### A handler that quiets its device is entered again, for the rest of the quantum

- **Where**: `src/sysc/core_complex.h`, `exec_b_transport` (the single-threaded one), and `clint_irq_cb` in `core_complex.cpp`.
- **What is wrong**: the core learns the level of its interrupt inputs from `clint_irq_cb`, a SystemC method. A method cannot run while the core's thread is running, and with a quantum the thread runs for a long time between yields. So when an interrupt handler quiets its device by writing to a register, and the device lowers its line, the core does not hear of it. It returns from the handler with the interrupt still pending, and takes it again, and again, until the quantum ends. With a PLIC the second claim reads 0, which an operating system treats as a spurious interrupt.
- **How to see it**: a quantum of 100 µs, a device whose interrupt line drops when it is written to, and a handler that writes to it and executes `mret`. Two interrupts ran the handler 634 times. In socpuppet that is `WhenAHandlerQuietsTheDeviceThatInterrupted.ItRunsOncePerInterrupt` in `tests/cpp/platform/cpu_test.cpp`, with the patch taken out.
- **What we do**: `cmake/patches/dbt-rise-riscv-interrupt-after-access.patch`. After a bus transaction, the thread yields for up to two delta cycles if anything is scheduled for the current time. One updates the signal and runs the method. Two does not rely on the kernel's order of evaluation. Only accesses that go over the bus pay for it, and memory reached by DMI does not. Measured speed on a loop was unchanged. 🧦 The adapter has a second copy of the yield, for a line the patch cannot know of: a write to one of the hart's registers that are its IMSIC's, which is how an interrupt that came as a message is claimed (`LetALineThatChangedBeHeard` in `src/socpuppet/models/dbt_rise_cpu.cpp`, held by `WhenAMessageArrivesAtTheImsicOfACpuThatRunsAheadOfTheClock`, where the handler ran 136 times without it).
- **Upstream fix**: the patch covers the single-threaded quantum keeper, which is what socpuppet builds. The multi-threaded `exec_b_transport` needs the same inside its `execute_on_sysc` call. An alternative that needs no yield: read the interrupt inputs directly at the points where the core checks for pending interrupts.
- **Kind**: bug.
- **When it lands**: drop the patch, and the adapter's copy if upstream's fix needs no yield.

### A core that goes to sleep does not let the clock catch up first

- **Where**: `src/sysc/core2sc_adapter.h`, `wait_until`, which is where `wfi` ends up.
- **What is wrong**: a core runs ahead of the simulation's clock by up to a quantum (temporal decoupling). When it executes `wfi` it waits for an event straight away, without first waiting out the time it is ahead by. So the simulation's clock stays behind what the core has done, by up to a quantum, for as long as the core sleeps. A platform that stops while its CPU sleeps reports a time that depends on the quantum. TLM-2.0's guidance for a temporally decoupled process is to synchronize before it waits for anything but time.
- **How to see it**: one core, a quantum of 50 µs, a program that writes once to a target which adds 3 µs to the access and then executes `wfi`. `sc_start()` returns with `sc_time_stamp()` at 0, not at 3 µs or later. socpuppet's scripted master is held to this by `WhenAScriptEndsAheadOfTheClock.TheClockCatchesUpBeforeTheRunEnds` in `tests/cpp/contracts/bus_master_test.cpp`. The CPU is not.
- **What we do**: nothing. The effect is bounded by the quantum.
- **Upstream fix**: synchronize the quantum keeper at the top of `wait_until`'s wait, after accounting for the cycles executed since the last sync.
- **Kind**: bug, or at least a surprise.
- **When it lands**: the test above can move into the contract that both masters pass.

### A debugger's register read is not answered by the simulation's thread

- **Where**: `src/iss/debugger/riscv_target_adapter.h`, `read_single_register`, `write_single_register` and the two that take every register at once. `read_mem` and `write_mem`, lower in the same file, show the other way: `srv->execute_synchronized(f)`.
- **What is wrong**: a register is copied straight out of the core's register file, on the GDB server's thread, whatever the simulation's thread is doing. A memory access is handed to the simulation's thread, which sees to it when the core has stopped. The server listens from the moment the platform is built, so a debugger can attach before the simulation has run at all, and a register read then is answered at once with what the register held before the core's first reset: a program counter of 0. The same read a moment later gives the reset vector.
- **How to see it**: attach, and read the program counter before the simulation is started. In `tests/python/test_gdb.py`, take `wait_for_the_cpu_to_stop` out of `run_with_debuggers` and sleep for a moment before `platform.run`: every test of where the CPU is stopped fails with 0. CI met it by chance on 2026-10-10, in one job and not in the others, the first time a test attached to the second CPU of two.
- **What we do**: the tests' debugger reads a byte of memory first (`GdbClient.wait_for_the_cpu_to_stop` in `tests/python/gdb_client.py`), which comes back only once the core is stopped where it starts. [boot-your-firmware.md](boot-your-firmware.md) has the run started before GDB is attached, which is the order that never sees it.
- **Upstream fix**: hand register accesses to the simulation's thread, as memory accesses are.
- **Kind**: bug.
- **When it lands**: delete `wait_for_the_cpu_to_stop`, and the debugger may attach whenever it likes.

### Every core adds its `sysc` command to core 0's debug adapter

- **Where**: `src/sysc/core_complex.cpp`, `core_complex::create_cpu`, lines 174 to 182: `tgt_adapter = srv->get_target(0); // FIXME: add core_id`.
- **What is wrong**: a core that is created while a GDB server exists asks it for target 0's adapter and adds its own `sysc` command there (`monitor sysc print_time`, `monitor sysc break <time>`), whether or not the server is that core's. With two cores and one debugger, on the core created first, the adapter ends up with two commands called `sysc`, one for each core. With a server for each core, every core after the first would still add its command to the first one's.
- **How to see it**: by reading, when M6 was planned. With a server for each core and without this patch, `monitor sysc print_time` is answered by the first core's debugger only, and the others get an empty answer. `test_each_cpu_tells_its_own_debugger_the_time_it_stopped_at` in `tests/python/test_gdb.py` fails that way.
- **What we do**: `cmake/patches/dbt-rise-riscv-gdb-server-per-core.patch`. A core asks for the server that was started for its own `vm` (`server::get(vm)`, which the patch to DBT-RISE-Core adds) and adds its command there. A core with no GDB port finds no server and adds nothing.
- **Upstream fix**: the same. It goes with "One GDB server per process" under DBT-RISE-Core above, and needs it.
- **Kind**: bug.
- **When it lands**: drop the patch.

### `monitor sysc break <time>` does not stop a sleeping core

- **Where**: `src/sysc/core_complex.cpp`, `cmd_sysc`, which gives the core's debug adapter a break condition, and DBT-RISE-Core's `target_adapter_base::check_break_on_pc`, the one place a break condition is looked at.
- **What is wrong**: the condition is checked before each instruction the core executes. A core asleep in `wfi` executes none, so it does not stop when the time comes: it stops at its first instruction after that, whenever an interrupt next wakes it. A debugger told to continue until then waits with it. With several cores, where stopping all of them at one moment of a boot is the use the command is made for, the ones that are asleep at that moment are the ones that do not stop.
- **How to see it**: the host with its three firmwares and a debugger on each CPU. Send each `monitor sysc break 150 ms` and `continue`. The SSD's stops at 150.088 ms and the host's at 151.9 ms, each at its first instruction after the time. The manager's does not stop at all: its firmware has been asleep since it let the host go at 5.6 ms, and its debugger hears nothing. Tried by hand in M8.
- **What we do**: nothing. [boot-your-firmware.md](boot-your-firmware.md) offers `monitor sysc print_time` and does not mention `break`.
- **Upstream fix**: have the break condition wake a sleeping core, for instance by having the wait in `core2sc_adapter.h`'s `wait_until` end at the time asked for as well as on an interrupt.
- **Kind**: missing feature.
- **When it lands**: the command can be documented, with a test of three cores stopped at one time.

### A transaction's delay loses a clock cycle, and whatever is less than a whole one

- **Where**: three places. `src/sysc/core_complex.cpp`, `read_mem` and `write_mem`: `auto incr = (local_time_post.value() - local_time_pre.value()) / curr_clk.read().value();`. `src/sysc/core2sc_adapter.h`, `notify_phase`: `if(cycle_incr > 1) this->instr_if.update_last_instr_cycles(cycle_incr);`. And `src/iss/arch/riscv_hart_common.h`, `update_last_instr_cycles`: `arch.cycle_offset += cycles - 1;`.
- **What is wrong**: the delay a target adds to a transaction is turned into whole cycles of the core's clock by an integer division, which throws the remainder away, and those cycles then take the place of the instruction's own cycle where they should be added to it. So an access that is delayed by d costs `floor(d / period) - 1` cycles more than one that is not, and nothing at all below two cycles. With socpuppet's 100 ns clock a target that adds 20 ns, or 100 ns, or 199 ns, adds nothing however many times it is reached, and one that adds 300 ns adds 200. A loosely-timed model's latency below two cycles is invisible to the firmware's clock.
- **How to see it**: by reading, a target that adds 150 ns to `delay` in `b_transport`, behind a core with a 100 ns clock, leaves the core's cycle count where a target that adds nothing leaves it. That has not been run on its own. What was run is Zephyr's disk test on the host across the die-to-die link, whose default is 20 ns a crossing, with a quantum of 0: the verdict comes exactly 5 ms later than with a link that adds nothing, which is the time before the host is let out of reset, after 4081 crossings. At 200 ns a crossing the run is 0.407 ms longer, which is 100 ns a crossing, and at 20 µs it is 81.0 ms longer, which is 199 parts in 200 of what the crossings come to. The figures are in [plan.md](plan.md), under what was measured in M7.
- **What we do**: nothing. The link's trace records carry the time each crossing arrived, so the link's own timing can still be tested. No test of socpuppet's needs a CPU to feel a delay of less than two cycles.
- **Upstream fix**: two changes, and the second may be as intended. Keep the remainder of the division and carry it into the next access, or account the delay as time on the quantum keeper and derive the cycles from that. And add an access's cycles to the instruction's own, unless an instruction is meant to take as long as its access and no longer, in which case only the lost remainder is the surprise.
- **Kind**: bug, or at least a surprise.
- **When it lands**: the link's default latency starts to cost simulated time, and the M7 figures in [plan.md](plan.md) want measuring again.

### The `time` register is read from a signal, which cannot say how far ahead its reader is

- **Where**: `src/sysc/core2sc_adapter.h`, `read_time`: `owner->mtime_i.get_interface() ? owner->mtime_i.read() : 0`. And `src/sysc/core_complex.h`, where `quantum_keeper` is `protected`.
- **What is wrong**: 🎓 a core runs ahead of the simulation's clock, by up to a quantum, and stamps each bus access with how far ahead it is, so that a target answers for the core's own time. `time` is read from an input signal, `mtime_i`, and a signal has the value it had when the simulation's clock last got there. So `time` lags the `mtime` register that the same core reads over the bus one instruction later, by up to a quantum: 1,000 ticks with socpuppet's 100 µs and a 10 MHz timer. Firmware that compares the two, or takes a time from one and a deadline from the other, sees the clock jump. A wrapper that wants to answer `time` properly needs the core's lead, and the quantum keeper that has it cannot be reached from outside.
- **How to see it**: `WhenACpusTimeIsConnectedToItsTimer` in `tests/cpp/platform/cpu_test.cpp`, with the read made with no lead: `time` reads 8000 where the timer's own register, read by the next instruction, reads 8196.
- **What we do**: no patch. The adapter (`dbt_rise_cpu.cpp`) answers `time` itself, and `timeh` on a 32-bit core, with `register_csr_rd`: a read of eight bytes from the timer through a socket of its own, carrying the lead as a bus access does. It gets the lead by deriving from `core_complex` (`CoreComplex::Lead`), which is all the derived class is for. `mtime_i` is left unbound.
- **Upstream fix**: give `read_time` a hook that is handed the core's local time, or make the quantum keeper's local time readable, so that a wrapper need not derive from the class to ask.
- **Kind**: bug, or at least a surprise.
- **When it lands**: `CoreComplex` can go.

### A core with supervisor mode can never take a supervisor's interrupt

- **Where**: `src/iss/arch/riscv_hart_msu_vp.h`, in `read_ie`, `write_ie`, `read_ip` and `write_ip`, and `check_interrupt`. The masks they start from are `mie_mip_mask` in `src/iss/arch/riscv_hart_common.h`.
- **What is wrong**: each of the four takes the mask for the privilege level of the CSR and then clears `0x777` from it, with the comment "clear H, S & U mode bits" (or `0x666` when user-level interrupts are on, which clears the supervisor's bits just the same). So bits 1, 5 and 9, the supervisor's software, timer and external interrupts, cannot be set in `mie`, and a write to `sie` changes nothing below bit 16. `sie` and `sip` are also variables of their own (`sie_csr`, `sip_csr`) and not views of `mie` and `mip`, and `check_interrupt` looks at `mip_csr & mie_csr` and nothing else. The rest is there: `mideleg` takes the three bits, an input line sets its bit of `mip`, and a delegated interrupt would trap into supervisor mode. But one can be pending and can never be enabled, so none is ever taken.
- **How to see it**: found by reading, planning M13, and then run. `WhenAnInterruptHandedDownToSupervisorModeArrivesWhileTheCpuSleepsThere` in `tests/cpp/platform/cpu_test.cpp`: a program on `rv64gc_msu` delegates bit 9 in `mideleg`, sets it in `sie`, drops to supervisor mode with `sstatus.SIE` set and sleeps, and the test raises input line 9. Without the patch the handler never runs. With `sie` alone mended, `sip` still reads zero in the handler. `WhenSupervisorModeSetsItsOwnSoftwareInterruptPending` is the third: a `csrs sip` of bit 1 that nothing comes of.
- **What we do**: `cmake/patches/dbt-rise-riscv-supervisor-interrupts.patch`. The four handlers clear the hypervisor's and the user's bits from the mask and leave the supervisor's. `sie` is read and written as `mie` through `mideleg`, and `sip` as `mip` the same way, of which supervisor mode may write only bit 1, its software interrupt. `sie_csr` and `sip_csr` are left declared and are no longer used. 🧦 The adapter brings input line 9 out as `supervisor_irq`. Four tests in `tests/cpp/platform/cpu_test.cpp` hold it, the three above and `WhenSupervisorModeEnablesInterruptsThatWereNotHandedDownToIt` for the gating by `mideleg`. ⚠️ Three things in the patch are by the specification's reading and nothing has run them: that supervisor mode cannot write the timer's or the external interrupt's bit through `sip`, the masks for a core with user-level interrupts (`FEAT_EXT_N`, which no registered core has), and the arms for `sieh` and `siph`, which no core registers and which would want `midelegh` if one did.
- **Upstream fix**: the same, and then take the two variables out. A slip beside it is left alone: `read_ip` tests `addr == mieh` where it means `miph`. ⚠️ And one thing the wider mask brings with it: machine mode can now write bit 9 of `mip`, as the specification says it may, but there that bit is the OR of what software wrote and the controller's line, and here both are the one bit, set and cleared when the line changes. A machine-mode write that clears it while the line is high loses the interrupt until the line next moves. Bits 7 and 11 always behaved so, and are mended by `dbt-rise-riscv-mip-read-only.patch`.
- **Kind**: bug.
- **When it lands**: drop the patch.

### A core with supervisor mode drops the instruction an interrupt arrives at, if it reads memory or a CSR

- **Where**: `src/iss/arch/riscv_hart_msu_vp.h`, `check_interrupt`: `this->reg.pending_trap = 0x80ULL << 24 | res << 16 | 1;`. The same line in `riscv_hart_m_p.h` and `riscv_hart_mu_p.h` is `res << 16 | 1`, under the same comment. And the check that follows every access to memory, to a CSR or to a reservation in the interpreters of `src/vm/interp/`: `if(this->core.reg.trap_state>=0x80000000UL) throw memory_access_exception();`.
- **What is wrong**: 🎓 an interrupt is taken between two instructions: the one it arrives at runs to its end, and the handler returns to the next. The interpreter does that by copying `pending_trap` into `trap_state` after each instruction, executing the next one, and then taking the trap with the address after it. Bit 31 of `trap_state` means something else: the instruction being executed has faulted, and an instruction looks for it after each access and stops if it is set. This hart sets that bit on a pending interrupt. So an instruction that begins with a read stops there: a load has read the bus and never writes its register, a CSR instruction that reads first (`csrr`, `csrs`, `csrc`, `csrrw` with a destination) changes nothing, and neither does an LR, an SC or an AMO. The interrupt is then taken with the address of the instruction after, so the one that stopped is never executed. A plain store is not lost, because its write comes before the check and nothing follows it. ⚠️ `csrrc a0, mstatus, 8` is among the lost, and that is how an operating system takes its interrupt lock. The two harts without supervisor mode leave the bit clear, which is why nothing had met this.
- **How to see it**: `WhenAnInterruptArrivesAtALoadOnTheCoreWithSupervisorMode` in `tests/cpp/platform/cpu_test.cpp`: a program sleeps until its interrupt line is high, switches interrupts on, and loads a word with its next instruction. The register it loaded into still holds what it held before. 🧦 It was met as something much stranger. Zephyr's disk test, the image unchanged, took a load fault at address 0x108 on `rv64gc_msu` and passed on `rv64imac_mp`: a timer interrupt had arrived at the `ld ra, 40(sp)` of a function's epilogue, so the function returned to an older return address and ran part of itself again with the wrong registers. The two cores' instruction traces are alike for 1.3 million instructions and part at that return.
- **What we do**: `cmake/patches/dbt-rise-riscv-interrupt-drops-instruction.patch`, which takes the bit off, as the other two harts have it. Nothing else reads it there: `enter_trap` takes the trap's kind from the low 16 bits and its cause from the 15 above.
- **Upstream fix**: the same line.
- **Kind**: bug.
- **When it lands**: drop the patch.

### Firmware can clear a pending timer or external interrupt, and the core then sleeps through it

- **Where**: `write_ip` in `src/iss/arch/riscv_hart_msu_vp.h` and `src/iss/arch/riscv_hart_m_p.h`, and by reading in `riscv_hart_mu_p.h`, which no socpuppet core uses. And `clint_irq_cb` in `src/sysc/core_complex.cpp`, which is why the bit does not come back.
- **What is wrong**: 🎓 `mip` is the register that says which interrupts are pending. Its bits for the machine timer (`MTIP`, bit 7) and for the machine external interrupt (`MEIP`, bit 11) are read-only in the specification: each says what its line says, and firmware ends the interrupt at the timer or the interrupt controller, by giving the one a new compare value or claiming from the other, not by writing the bit. These harts take the write. ⚠️ `clint_custom_irq_mask`, which the two without supervisor mode build their mask from, is not the custom bits its name suggests: it is the low sixteen by default, and the low 32 or 64 once `set_clint_irq_num` has run. And the core is told of an interrupt line only when the line changes (`clint_irq_cb` acts on `event()`), so a bit that firmware has cleared stays clear for as long as the line stays high. A core that then executes `wfi` sleeps with the line high, and if nothing else is due it sleeps for ever. Zephyr does both halves on every timer interrupt. Its interrupt entry clears the bit of the interrupt it is about to handle (`soc/common/riscv-privileged/soc_irq.S`: `csrrc t1, mip, t0`), which does nothing on a hart where the bit is read-only. Its timer driver then writes the compare value it worked out, and when that is already in the past the line never falls. The external interrupt's line stays high the same way when its controller has another interrupt waiting after a claim, which no firmware here has been seen to meet.
- **How to see it**: `WhenAProgramClearsTheTimerInterruptInMipWhileItsLineIsHigh` and `WhenAProgramClearsTheExternalInterruptInMipWhileItsLineIsHigh` in `tests/cpp/platform/cpu_test.cpp`, with the patch taken out, each on `rv64gc_msu` and on `rv64imac_mp`: a program sleeps until the line is high, clears its bit of `mip`, executes `wfi` again and never comes back. 🧦 It was met as Zephyr's own `tests/kernel/common` stopping half way through `test_timeout_order` on the host, with the simulation out of work: `mtimecmp` behind `mtime`, the line high, `mip` zero and the CPU asleep. All nine of its scenarios and two of `tests/kernel/sched/schedule_api` stopped that way ([twister-spike.md](twister-spike.md)). 💡 The same images passed on the 32-bit boards, whose hart has the same fault, and why is by reading and has not been run: a 32-bit Zephyr writes the compare value in three halves, the high one to all ones first, so the line falls and a value in the past raises it again, which the core hears.
- **What we do**: `cmake/patches/dbt-rise-riscv-mip-read-only.patch` takes bits 7 and 11 out of what a write to `mip` may change, in the two harts socpuppet builds.
- **Upstream fix**: the same in all three harts, and for bit 3 as well, machine mode's software interrupt, which the specification makes read-only alike. No line of socpuppet's reaches it, so the patch leaves it. Bit 9 is the supervisor-interrupts entry's above: it wants the OR of what software wrote and what the line says.
- **Kind**: bug.
- **When it lands**: drop the patch.

### A trap that `sret` raises is thrown away, and an interrupt can be taken inside an exception's handler

- **Where**: `src/iss/arch/riscv_hart_msu_vp.h`, `leave_trap`, and `enter_trap` in all three harts.
- **What is wrong**: two things, both ⚠️ found by reading while the entry above was checked, and neither run. `leave_trap` sets an illegal-instruction trap in `trap_state` when supervisor mode executes `sret` with `mstatus.TSR` set, and then ends with `trap_state = pending_trap` whichever branch it took, which overwrites it, with `NEXT_PC` left at `0xffffffff`. And `enter_trap` clears `pending_trap` only when what it is taking is an interrupt. If an interrupt is pending and the instruction it arrives at raises an exception of its own (an `ecall`, a fault), the exception is taken, the interpreter copies the old `pending_trap` back, and the interrupt is taken one instruction into the exception's handler, with interrupts off, over the top of `mepc` and `mcause`.
- **How to see it**: by reading. For the second, an `ecall` at the instruction a pending and enabled interrupt arrives at.
- **What we do**: nothing. Zephyr on the host makes no `ecall` and never runs in supervisor mode. Linux under OpenSBI does both, in M20.
- **Upstream fix**: return from `leave_trap` after raising the trap. And have `enter_trap` work `pending_trap` out again (`check_interrupt`) once it has changed `mstatus`, whatever it took.
- **Kind**: bug.
- **When it lands**: nothing to delete.

## softvector

[Minres/softvector](https://github.com/Minres/softvector), a submodule of DBT-RISE-RISCV.

### `std::make_signed` specialized for 128-bit integers

- **Where**: `src/vector_functions.hpp`, lines 57 to 66.
- **What is wrong**: it specializes `std::make_signed` for `__uint128_t`, `__int128_t` and a helper type. The standard forbids specializing that trait, and Clang treats it as an error.
- **How to see it**: compile with Clang.
- **What we do**: no patch. `cmake/Dependencies.cmake` puts `-Wno-invalid-specialization` on the `softvector` target, privately, for Clang and Apple clang. Only newer Clangs have the diagnostic (Apple clang 21 does, the one on GitHub's `macos-15` runners does not), so how it shows depends on the compiler's version.
- **Upstream fix**: a trait of its own, in its own namespace, in place of the specializations.
- **Kind**: portability.
- **When it lands**: delete the compile option.

## VPV-Peripherals

[VP-Vibes/VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals), pinned at `8c70afc`. socpuppet borrows peripheral models from it: the PULPino UART, behind `src/socpuppet/models/ns16550.cpp`, the Minres ACLINT, behind `src/socpuppet/models/machine_timer.cpp`, and the RISC-V PLIC, behind `src/socpuppet/models/plic.cpp`.

### The ACLINT ignores a compare value written at time zero

- **Where**: `minres/aclint.cpp`, `update_mtime`, the condition `sc_core::sc_time_stamp() > SC_ZERO_TIME && mtime_clk_period > SC_ZERO_TIME`.
- **What is wrong**: `update_mtime` is what raises the timer interrupt and schedules the next look at the compare registers. At simulated time zero it does nothing. So a `mtimecmp` written at time zero is stored and never acted on: no event is scheduled, and the interrupt never comes, however long the simulation runs.
- **How to see it**: write `mtimecmp` = 100 at time zero, with a tick of 100 ns, and run for 20 µs. The interrupt output stays low. In socpuppet that is `MachineTimerContract.ACompareValueSetAtTheVeryStartIsHonoured` in `tests/cpp/contracts/machine_timer_contract.h`, with the patch taken out.
- **What we do**: `cmake/patches/vpv-peripherals-aclint-time-zero.patch` drops the first half of the condition. The second half already covers the case the first was probably there for, a tick period that is not known yet.
- **Upstream fix**: the same.
- **Kind**: bug.
- **When it lands**: drop the patch.

Two more things read in the same file and not acted on:

- `const int lfclk_mutiplier = 10; // hardcoded for unit test` is declared and never used.
- The write callbacks for `mtimecmp` and `msip` call `wait()` when the access arrives with a delay, so they only work when the write comes from a SystemC thread. A write from a method would be a SystemC error.

### The ACLINT wakes for every tick once anything reads its count as a signal

- **Where**: `minres/aclint.cpp`, the end of `update_mtime`: `if(mtime_o.get_interface()) { mtime_evt.notify(mtime_clk_period); }`.
- **What is wrong**: `mtime_o` is the count as a 64-bit output, for a core's `time` register. With nothing bound to it the model sleeps until the next compare value is due. With something bound it wakes itself every tick to write the new count: ten million times a simulated second at 10 MHz, and with each a delta cycle of the kernel's. On the host's disk test that would be six million wakes for a run that takes under half a second of wall clock today.
- **How to see it**: by reading. It has not been measured, because socpuppet does not bind the output.
- **What we do**: no patch. The timer's adapter (`machine_timer.cpp`) has a second target socket, `time`, and a CPU reads the count through it when its firmware reads `time`. That is the `mtime` register read with the reader's lead, which a signal could not carry either (see DBT-RISE-RISCV above).
- **Upstream fix**: a way to ask for the count at a given time, such as a TLM socket or a function, beside the signal. Or write the signal only when it is read, which SystemC has no hook for.
- **Kind**: efficiency.
- **When it lands**: nothing to delete. The socket carries the reader's lead, which the signal never can.

### A write to the ACLINT's `mtime` adds the time since its last update

- **Where**: `minres/aclint.cpp`, the write callback of `mtime`: `reg.put(data); this->update_mtime();`.
- **What is wrong**: `update_mtime` adds the ticks that have passed since it last ran to whatever the register holds. Run straight after a write, it adds them to the value just written. So a count written as N, 5 µs after the model last updated itself, reads back as N + 50.
- **How to see it**: `MachineTimerContract.AWriteThroughTheTimeSocketIsRefusedAndTheCountGoesOn` in `tests/cpp/contracts/machine_timer_contract.h`, with the refusal taken out of `MachineTimer::ReadTime`: a write of 1,000,000 at 5 µs is read back as 1,000,050.
- **What we do**: nothing. Zephyr never writes `mtime`, and no test of socpuppet's sets the count to a value it then relies on.
- **Upstream fix**: bring `last_updt` up to now before the written value is stored, so that nothing is owed.
- **Kind**: bug.
- **When it lands**: nothing to delete.

### The PLIC reads its last source's priority from past the end of an array

- **Where**: `rvi/gen/plic_regs.h`, `r_priority` and the `priority` register, both sized `NUM_SOURCES`, and `NUM_PENDING`.
- **What is wrong**: source IDs run from 1 to `NUM_SOURCES`, and ID 0 is reserved but has a priority register and a pending bit of its own. So there are `NUM_SOURCES + 1` of each. With arrays of `NUM_SOURCES`, the last source has no priority register on the bus (a write to it is refused), and `get_source_irq` reads `r_priority[NUM_SOURCES]`, one past the end, on every evaluation. What it finds there is the pending word, so the last source behaves as if it had a very high priority.
- **How to see it**: `plic<31, 1>`, source 3 with priority 2, source 31 with priority 1, both pending. A claim returns 31. In socpuppet that is `InterruptControllerContract.TheLastSourcesPriorityIsTheOneItWasGiven` in `tests/cpp/contracts/interrupt_controller_contract.h`, with the patch taken out.
- **What we do**: `cmake/patches/vpv-peripherals-plic-last-source.patch` sizes both by `NUM_SOURCES + 1`.
- **Upstream fix**: the same.
- **Kind**: bug.
- **When it lands**: drop the patch.

### The PLIC does not look again when its registers are written

- **Where**: `rvi/plic.h`, the constructor. Only the claim/complete register has callbacks.
- **What is wrong**: the interrupt output is worked out when a source's line rises and when a claim is read, and at no other time. A source that is already pending when the firmware enables it, gives it a priority, or lowers the threshold below it does not interrupt until some other source's line happens to rise.
- **How to see it**: raise a source's line, then set its priority and its enable bit. The output stays low. In socpuppet that is `InterruptControllerContract.ASourceEnabledWhileItsLineIsAlreadyHighInterrupts`, with the patch taken out.
- **What we do**: `cmake/patches/vpv-peripherals-plic-look-again.patch` gives the priority, enable and threshold registers write callbacks that store the value and call `handle_pending_irq` for every context.
- **Upstream fix**: the same.
- **Kind**: bug.
- **When it lands**: drop the patch.

### The PLIC treats every source as edge-triggered

- **Where**: `rvi/plic.h`, `source_irq_cb` (sensitive to rising edges only) and `claim_complete_write_cb`.
- **What is wrong**: a source becomes pending on a rising edge of its line, and completion only marks it free to be triggered by the next edge. 🎓 The PLIC specification's sources are level-sensitive by default: if the line is still high when the handler completes, the source is pending again at once. That is how a device with more to say, such as a UART with more bytes waiting, gets its handler run again. Here such a device is never serviced a second time, because its line never rises again.
- **How to see it**: raise a line, claim, and complete without lowering the line. The output stays low. In socpuppet that is `InterruptControllerContract.CompletingASourceWhoseLineIsStillHighInterruptsAgain`, with the patch taken out.
- **What we do**: `cmake/patches/vpv-peripherals-plic-level-sources.patch`. On completion, a source whose line reads high is marked pending again and the outputs are worked out afresh.
- **Upstream fix**: the patch covers the build with `SC_SIGNAL_IF`, where an input's level can be read. The build with TLM signal sockets needs to remember each source's last level to do the same. A per-source choice of edge or level, as VCML's PLIC has, would serve both kinds of device.
- **Kind**: bug.
- **When it lands**: drop the patch.

### The PLIC forgets a request made while its source is claimed

- **Where**: `rvi/plic.h`, `source_irq_cb` and `claim_complete_write_cb`.
- **What is wrong**: a rising edge on a source that has been claimed and not yet completed is dropped. With `vpv-peripherals-plic-level-sources.patch` a line that is still high at completion is heard, but a line that only pulsed is not. 🎓 That is how a message-signalled interrupt (MSI) looks once something has turned it into a wire: an edge, with nothing to hold the line up until the handler has listened. A handler that had already looked at its device when the pulse came returns, and the device waits for ever. The PLIC specification leaves the choice open for an edge-triggered source (a gateway may ignore the further edges or count them), so this is a gap, not a defect.
- **How to see it**: pulse a line, claim, pulse it again, complete. The output stays low. In socpuppet that is `InterruptControllerContract.ASourceThatPulsesWhileItIsClaimedInterruptsAgainWhenCompleted`, with the patch taken out.
- **What we do**: `cmake/patches/vpv-peripherals-plic-edge-while-claimed.patch`. An edge on a claimed source is remembered, and at completion the source is pending again, once however many edges there were. An edge on a source that is still pending is not remembered: its handler has yet to look, so one interrupt covers both.
- **Upstream fix**: the patch covers the build with `SC_SIGNAL_IF`. The build with TLM signal sockets can do the same in its own `source_irq_cb`, which is already told which source changed. A per-source choice of edge or level would let a level-triggered source keep the stricter reading, where only the level at completion counts.
- **Kind**: missing feature.
- **When it lands**: drop the patch.

### The PLIC and the ACLINT write their interrupt outputs from whichever process is running

- **Where**: `rvi/plic.h`, `write_irq`, reached from `source_irq_cb` (the model's own method) and from the claim/complete callbacks, which run in the thread of whoever is accessing the register (with `cmake/patches/vpv-peripherals-plic-look-again.patch`, the priority, enable and threshold writes reach it the same way). And `minres/aclint.cpp`, `update_mtime`, which writes `mtime_int_o` and is both a method of the model's own and what the `mtime` and `mtimecmp` write callbacks call.
- **What is wrong**: 🎓 SystemC lets one process write a signal in a delta cycle, and reports `E115` ("cannot have more than one driver") when a second one changes it in the same delta. Each model's output is written by its method when something of its own happens (a source's line rises, the count reaches the compare value) and by the caller's thread when a register is written. So a line that rises in the same delta cycle as a PLIC register write ends the simulation, and so does a compare value written in the instant the timer reaches it, as a tick handler does. A device that interrupts at time zero while the firmware is enabling it was enough to see the first.
- **How to see it**: `InterruptControllerContract.ASourceThatRisesInTheSameDeltaCycleAsAnEnableWriteInterrupts` in `tests/cpp/contracts/interrupt_controller_contract.h` and `MachineTimerContract.MovingTheCompareValueAheadInTheInstantTheCountReachesItEndsTheInterrupt` in `tests/cpp/contracts/machine_timer_contract.h`, with the adapters binding the outputs straight to checked signals.
- **What we do**: no patch. Each adapter (`plic.cpp`, `machine_timer.cpp`) binds the output to a signal that does not check its writers, and copies it to `irq` from one method of its own. The CPU sees the line one delta cycle later than it would otherwise, which nothing notices.
- **Upstream fix**: have `write_irq` and `update_mtime` only note the new level and notify an event, and one `SC_METHOD` per model write the output.
- **Kind**: bug.
- **When it lands**: the adapters can bind the outputs to `irq` directly again.

### The ACLINT's and the PLIC's registers are indeterminate until reset is pulsed

- **Where**: `minres/gen/aclint_regs.h` and `rvi/gen/plic_regs.h`, the storage declarations (`uint64_t r_mtime;`, `std::array<uint32_t, ...> r_priority;` and the rest).
- **What is wrong**: the storage has no initial value, and the registers get their reset values only when `rst_i` moves. That is how hardware behaves, so it is defensible. But a platform that ties `rst_i` low, as one with no reset controller does, starts with whatever was in memory. With an ordinary allocator that is usually zero, which looks like it works.
- **How to see it**: build with AddressSanitizer, which fills new memory with a pattern, tie `rst_i` low and read `mtime` at time zero. In socpuppet, 15 tests failed in the sanitizer build and nowhere else.
- **What we do**: no patch. The adapters (`machine_timer.cpp`, `plic.cpp`) call `reset_start()` and `reset_stop()` on the registers as the simulation starts.
- **Upstream fix**: value-initialize the storage, or reset the registers in `start_of_simulation`.
- **Kind**: a surprise more than a bug.
- **When it lands**: the adapters can stop doing it.

### The PULPino UART's line status says "data ready" until it is told otherwise

- **Where**: `pulpino/uart.h`, `b_transport_ext`, and the read callback of `rbr_thr_dll_`.
- **What is wrong**: 🎓 a 16550's line status has a bit that says a received byte is waiting, which clears when the byte is read. Here the bit is set and cleared only by `b_transport_ext`, a socket whose one message is "a byte is waiting" or "none is". Reading the receive register asks the serial line's socket for the byte and leaves the bit as it was. So whoever is on the serial line has to say "none is" after the last byte, and "one is" again after each of the others, or firmware that reads until the bit clears reads for ever. And `b_transport_ext` reads four bytes of the payload whatever length the payload says it has.
- **How to see it**: `UartContract.AByteThatComesInIsReadFromTheReceiveRegisterAndThenThereIsNone` in `tests/cpp/contracts/uart_contract.h`, with the adapter's telling after a read taken out: the line status still says "data ready" with nothing left.
- **What we do**: no patch. The adapter (`ns16550.cpp`) keeps the bytes that have come in, answers the model's request for each, and tells the model after every one whether another waits, in a payload of four bytes.
- **Upstream fix**: keep a count, or a FIFO, of what has come in, and clear the bit when the last is read. Read as many bytes of a payload as it has.
- **Kind**: bug.
- **When it lands**: the adapter's telling after each read can go.

### The PULPino UART works its interrupt out from a queue of events, and loses track

- **Where**: `pulpino/uart.h`, `send_interrupt_process` and everything that pushes to `interrupt_event_q_`.
- **What is wrong**: 🎓 a 16550's interrupt line is a level, and its identification register (IIR) says why the line is high. Two reasons matter to a console. "A received byte is waiting" lasts until the byte is read. "The transmit register has emptied" is acknowledged by reading the IIR while it is the reason given, and happens again when the next byte has gone. Here each register access pushes a "set" or a "reset" event, and a thread folds the events into the IIR. Five things go wrong:
  - Enabling an interrupt whose cause is already there raises nothing: a byte that came in before the receive interrupt was enabled, and a transmit register that is empty when the transmit interrupt is enabled. A driver starts to transmit by enabling that interrupt and waiting for it, so Zephyr's would never send its first byte.
  - When a "set" and a "reset" are folded together the resets are dropped, so a handler that reads two bytes with nothing between leaves the line high with nothing waiting, and the IIR says a byte is.
  - With both pending the two reasons are or-ed into the IIR, which then reads as the code for a third, the line-status interrupt, and a driver services neither. And any read of the IIR acknowledges the transmit interrupt, whatever the read reported.
  - Disabling an interrupt in the enable register does not lower the line.
  - The IIR reads as zero until the first event, which says "pending" with a reason the model does not have. And the line-status interrupt is raised when "data ready" changes, which is not what it is for.
- **How to see it**: six tests of `UartContract` in `tests/cpp/contracts/uart_contract.h` fail with the patch taken out: `EnablingTheReceiveInterruptWithAByteAlreadyWaitingInterrupts`, `ReadingTwoBytesOneStraightAfterTheOtherEndsTheInterrupt`, `EnablingTheTransmitInterruptWhileNothingIsBeingSentInterrupts`, `ReadingWhichInterruptIsPendingEndsTheTransmitInterrupt`, `WithBothPendingAReceivedByteIsSaidFirstAndTheTransmitterAfterIt` and `DisablingTheTransmitInterruptWhileItIsPendingEndsIt`. So does `TestWhenFirmwareSleepsUntilTheUartInterrupts` in `tests/python/test_uart.py`, where a handler echoes what is typed.
- **What we do**: `cmake/patches/vpv-peripherals-uart-interrupt-from-state.patch`. The queue goes. The model keeps one bit of its own, "the transmit register has emptied and the IIR has not said so yet", which is set when a byte is sent and when the transmit interrupt goes from disabled to enabled, and cleared by an IIR read that reports it. The IIR and the line are then worked out from what is true at that moment: the enable register, the line status's "data ready" bit, and that one bit. The line is still written by the model's one thread, a delta cycle after whatever changed. The line-status interrupt is left out, since the model has no line errors to report.
- **Upstream fix**: the patch as it is. A model with a transmitter that takes time would set the bit when the byte has gone, where the patch sets it at once. The patch does not reset the bit, or the enable register, when `rst_in_` moves; the enable register was not reset before it either.
- **Kind**: bug.
- **When it lands**: drop the patch.

### The APLIC delivers over a line only

- **Where**: `rvi/aplic.cpp`, `rvi/aplic.h`, and the registers in `rvi/aplic.rdl` and `rvi/gen/aplic_regs.h`.
- **What is missing**: 🎓 an APLIC has two ways to deliver an interrupt, and firmware chooses with the DM bit of `domaincfg`. Over a line to the hart, where the hart claims the interrupt at the APLIC, as with a PLIC. Or by message (MSI), where the APLIC writes the interrupt's identity to the page of the hart's IMSIC and forgets it. The model has the first, and says so at the top of the file. A platform whose harts have IMSICs needs the second, and so does any Linux or Zephyr that is built for one.
- **How to see it**: `AplicContract` in `tests/cpp/contracts/aplic_contract.h`, which is the second way and nothing else. Without the patch the adapter does not compile, since the model has no socket for a message to leave by.
- **What we do**: `cmake/patches/vpv-peripherals-aplic-msi-mode.patch`. It adds:
  - `mmsiaddrcfg` and `mmsiaddrcfgh`, and the address of a hart's page worked out from them as the specification has it;
  - the MSI form of `target`, hart and identity, when DM is set;
  - `msi_o`, a socket the messages leave by, and one thread that sends them, since a wire changes in a method and a register is written in the caller's thread and whatever is on the way to the hart may wait;
  - `setipnum_le`, which sets a level-sensitive source pending only while its input is asking. In MSI mode that is how software has a source looked at again after its handler, and Linux's driver uses it;
  - `clrienum`, which the model had as a register that did nothing;
  - a source that is made level-sensitive while its input is already asking is pending at once, and one that is made inactive is no longer pending or enabled. The model keeps each wire's level to know the first.
- **Upstream fix**: offer the patch. Three of its points change the direct way of delivering too: `setipnum_le`, `clrienum`, and what a write to `sourcecfg` does to the pending and enable bits. And `msi_o` is a socket that every user of the model now has to bind, which one that only delivers over a line should not have to: offer it with a way to leave it unbound. It was written against the build with `SC_SIGNAL_IF`, and is tested there only. There is still no domain for supervisor mode, no `genmsi`, no `setipnum`, `clripnum` or `setipnum_be`, and no lock bit in `mmsiaddrcfgh`. `setip` and `in_clrip` do not follow the rules for a level-sensitive source in MSI mode, `domaincfg` does not read `0x80` in its top byte, and `target` is not read-only while its source is inactive.
- **Kind**: missing feature.
- **When it lands**: drop the patch.

### The APLIC has an input for each of 1,022 sources, and wants every one bound

- **Where**: `rvi/aplic.h`, `num_irq`, and the constructor in `rvi/aplic.cpp`.
- **What is wrong**: the number of sources is a CCI parameter that is read as the model is constructed, with 1023 as its default, and with `SC_SIGNAL_IF` each source is an `sc_in<bool>`, which SystemC insists be bound. That makes 1,023 inputs, numbered from 0, for sources 1 to 1,022: input 0 is never looked at, and source 1,023, which the register map has room for, has no input (its `sourcecfg` can be written, and the model then indexes one past its inputs). A platform with three devices binds 1,020 inputs to nothing. To have fewer, a preset value has to be in the CCI broker before the model exists. And two things are easy to miss beside it: a write to `target` whose low byte is zero is dropped without a word in the direct way of delivering, and a source in the "detached" mode is still listened to on its wire.
- **How to see it**: construct the model and bind three inputs.
- **What we do**: no patch. The adapter (`aplic.cpp`) brings out 31 sources, binds the other inputs to one signal that nothing writes, and answers itself for the registers of the sources it does not bring out, so that none of them can be set up.
- **Upstream fix**: make the inputs optional (`sc_in_opt`, as the ACLINT's are), or the number of sources a constructor argument.
- **Kind**: a surprise more than a bug.
- **When it lands**: the adapter can stop binding what it does not use.

### The always-on block has a watchdog's registers and no watchdog

- **Where**: `sifive/aon.cpp`, `sifive/aon.h`, and the reset value of one register in `sifive/aon.rdl` and `sifive/gen/aon_regs.h`.
- **What is missing**: 🎓 SiFive's FE310 has an always-on block with a watchdog in it, which Zephyr and Linux both have a driver for. The model has all the block's registers and nothing behind any of them: what is written is read back, nothing counts, and its reset output only follows the reset button. A firmware's watchdog driver sets it up and it never bites.
- **How to see it**: `WatchdogContract` in `tests/cpp/contracts/watchdog_contract.h`. Without the patch the adapter does not compile, since the model has no output for the watchdog's interrupt.
- **What we do**: `cmake/patches/vpv-peripherals-aon-watchdog.patch`. It adds the watchdog as the FE310's manual has it:
  - a count of ticks of the 32,768 Hz clock while `wdogcfg` says to count, worked out when it is read and not stepped a tick at a time, so that an idle watchdog schedules nothing;
  - `wdogs`, the count shifted right by the scale, and the moment it reaches `wdogcmp`;
  - at that moment, with `rsten`, a pulse of `rst_o` one tick long, and the watchdog back as it is out of reset; without it, the `ip0` bit, which stays until firmware clears it, and a new output for it, `wdog_irq_o`, optional so that a platform that does not bind it still elaborates;
  - `zerocmp`, the key that every write wants first and uses up, and the value that feeds;
  - `wdogcmp` out of reset as `0xFFFF`, where it was zero, which would bite the moment the watchdog was started.
- **Upstream fix**: the patch as it is, as an offer of a feature. It leaves the rest of the block alone: the real-time clock and the power manager are still registers and nothing more. `rst_o` now has one process that writes it, where the button's callback wrote it directly. Two things it does not do, to say when offering it: the count goes by the simulation's clock and ignores how far ahead of it an accessing CPU is, where the ACLINT counts that in, and it does not wrap at 31 bits.
- **Kind**: missing feature.
- **When it lands**: drop the patch.

### The flash chip ends the process at an access past its 256 MB

- **Where**: `generic/spi_mem.h`, `scc::memory<256_MB, scc::LT> mem`, reached through `spi_t`'s blocking and debug transport, and so through `minres/qspi`'s `xip_sck`.
- **What is wrong**: the chip is 256 MB whatever a platform wants, with no parameter for it, and an access that starts past the end does not come back with an address error. The process ends: "pointer being freed was not allocated".
- **How to see it**: a read at `0x1000_0000` through `xip_sck`. M14's spike did it ([boot-spike.md](boot-spike.md)). In socpuppet, `AnAccessThroughAFlashsWindowFarPastItsSize` in `tests/cpp/platform/spi_flash_test.cpp` with the adapter's own check taken out.
- **What we do**: no patch. The adapter (`src/socpuppet/models/spi_flash.cpp`) has a size of its own and turns an access past it away before the chip sees it.
- **Upstream fix**: a size parameter for the chip, and an address-error response past it.
- **Kind**: bug.
- **When it lands**: the adapter's check can go, with its size given to the chip.

### The flash's memory window takes a write

- **Where**: `minres/qspi.cpp`, the `xip_sck` socket, and `generic/spi_mem.cpp`, which hands what arrives to its memory.
- **What is wrong**: 🎓 a flash mapped for execute in place is read through that window, and written by erase and program commands to its controller. The model's window passes a write on to the chip's memory, which takes it, so firmware that stores to its flash by mistake changes it and is told nothing.
- **How to see it**: a write through `xip_sck` and a read of the same address. In socpuppet, `ABusWriteThroughAFlashsWindow` in `tests/cpp/platform/spi_flash_test.cpp` with the adapter's own check taken out.
- **What we do**: no patch. The adapter answers a write through its window with a command error. A debugger's write is passed on, on purpose: it is how a platform fills the flash.
- **Upstream fix**: refuse a write command in `xip_sck`'s blocking transport.
- **Kind**: bug.
- **When it lands**: the adapter's check can go.

### The flash's memory window says direct access is allowed, and cannot grant it

- **Where**: `minres/qspi.cpp`, `xip_sck`, which registers a blocking and a debug transport and no `get_direct_mem_ptr`, and `generic/spi_mem.h`, whose `scc::memory` sets the DMI-allowed hint on what it answers.
- **What is wrong**: 🎓 a target that sets the hint on a transaction is telling its initiator that a pointer to its memory is worth asking for. The chip's memory sets it, the hint rides back out through the window, and a CPU model that then asks is refused: neither the window nor an SPI socket has a way to pass the request on. A CPU asks again at every access.
- **How to see it**: a read through `xip_sck`, the hint on the transaction that comes back, and a request for direct memory access that is then refused. In socpuppet, `AFlashsWindow.GrantsNoDirectMemoryAccess` in `tests/cpp/platform/spi_flash_test.cpp` with the adapter's own line taken out.
- **What we do**: no patch. The adapter clears the hint on what comes back through its window. socpuppet wants no direct access there in any case: a boot ROM's reads are meant to show in a trace.
- **Upstream fix**: clear the hint in `xip_sck`'s blocking transport, or pass a request for direct memory access on to the chip.
- **Kind**: bug.
- **When it lands**: nothing to delete. The adapter keeps its line, for the trace's sake.

### `pulpino/uart.h` does not include what it uses

- **Where**: `pulpino/uart.h`, lines 80 to 82.
- **What is wrong**: it uses `tlm_utils::simple_initiator_socket` and `tlm_utils::simple_target_socket` and includes neither header. It compiles only if whoever includes it has included them first.
- **How to see it**: a source file whose first include is `pulpino/uart.h`.
- **What we do**: no patch. `ns16550.cpp` includes the two socket headers first, and switches clang-format off around the include so that sorting does not move it.
- **Upstream fix**: add the two `#include` lines to the header.
- **Kind**: bug.
- **When it lands**: sort the include with the others.

### Every library links all of SCC

- **Where**: the `CMakeLists.txt` of each family, for example `target_link_libraries(${PROJECT_NAME}_pulpino INTERFACE scc)`.
- **What is wrong**: `scc` is SCC's umbrella target, and it includes SCC's AXI and CHI protocol library. That library needs Boost.Statechart, and with Apple clang it does not compile (see the LWTR4SC entry under SCC above). The register-based models here use SCC's register and target classes only, which is the `scc::components` target.
- **How to see it**: link `vpvper_pulpino` from a project that fetches Boost library by library, without `statechart`.
- **What we do**: no patch. `cmake/Dependencies.cmake` fetches the sources without running the project's CMake, and each adapter adds the include directory and links `scc::components` itself.
- **Upstream fix**: link the SCC components each family uses in place of the umbrella.
- **Kind**: build.
- **When it lands**: use the project's own targets.

## Zephyr

[zephyrproject-rtos/zephyr](https://github.com/zephyrproject-rtos/zephyr), release `v4.4.2`. Nothing in Zephyr's tree is patched: `firmware/build.sh` builds a clean clone. Each of these is worked around in socpuppet's Zephyr module, `python/socpuppet/zephyr_module`. 🎓 The first five come from the same place. Zephyr's PCIe and NVMe code grew up on PCs, where firmware has set the bus up before Zephyr starts, and on Arm boards with one particular interrupt controller. A RISC-V board with neither is new ground. The two after them are about the flash API, which the SSD's firmware uses for its NAND, and which was written with a microcontroller's own flash in mind. The last are about RISC-V's Advanced Interrupt Architecture, whose two drivers are new in this release and have no board in Zephyr's tree that uses them.

### A PCIe controller can deliver MSI only through an Arm GICv3 ITS

- **Where**: `drivers/pcie/host/pcie_ecam.c`, `pcie_ecam_msi_device_setup`.
- **What is wrong**: the generic ECAM driver does everything a simple root complex needs (configuration access, and placing BARs in the windows that `ranges` gives) except interrupts. Its `msi_device_setup` is written against the GICv3 ITS and returns "no vectors" without `CONFIG_GIC_V3_ITS`. Outside x86, which has its own path, that is the only way Zephyr has to deliver a message-signalled interrupt. A board with any other MSI controller cannot use the driver, and Zephyr's NVMe driver cannot work without MSI-X: it has no polled mode.
- **How to see it**: give a RISC-V board a `pci-host-ecam-generic` node and an `nvme-controller`. The NVMe driver logs `Could not allocate 2 MSI-X vectors`.
- **What we do**: a controller driver of our own, `drivers/pcie/socpuppet_pcie.c`, for the compatible `socpuppet,pcie`. It repeats the ECAM driver's configuration and BAR handling for one memory window, and its `msi_device_setup` sends each vector to the IMSIC that the node's `msi-parent` names: the IMSIC's page is the address and an identity the data, and the node says which identities are the device's (`socpuppet,msi-identities`). 🦜 Until M13 the parent was an MSI-to-PLIC bridge of socpuppet's own, which went when the host's PLIC did.
- **Upstream fix**: let the ECAM driver hand MSI setup to the device its `msi-parent` property names, through a small driver API for "something that takes interrupt messages": give me an address, a data value and an interrupt for each of N vectors. The ITS code would be one implementation of it, and a RISC-V IMSIC another, handing out identities itself.
- **Kind**: missing feature.
- **When it lands**: `socpuppet_pcie.c` goes, if Zephyr's IMSIC driver is given that API, and the root complex's node becomes a `pci-host-ecam-generic`. It has the `msi-parent` already.

### MSI-X does not link in a kernel with no MMU

- **Where**: `drivers/pcie/host/msi.c`, `map_msix_table_entries`.
- **What is wrong**: it reaches a device's MSI-X table with `k_mem_map_phys_bare()`, which `kernel/mmu.c` defines only with `CONFIG_MMU`. The wrapper made for drivers, `device_map()` in `include/zephyr/sys/device_mmio.h`, already does the right thing without an MMU: the address is the physical address. The NVMe driver uses that wrapper for its own registers, in the same call chain.
- **How to see it**: build anything with `CONFIG_PCIE_MSI_X=y` for a board with no MMU. The link fails with an undefined reference to `k_mem_map_phys_bare`.
- **What we do**: `drivers/pcie/map_without_mmu.c` defines the function for a kernel with no MMU, as "the address you came with".
- **Upstream fix**: call `device_map()` in `map_msix_table_entries`.
- **Kind**: build.
- **When it lands**: delete the file and `CONFIG_SOCPUPPET_MAP_WITHOUT_MMU`.

### Nothing switches on memory decoding for an NVMe drive

- **Where**: `drivers/disk/nvme/nvme_controller.c`, `nvme_controller_pcie_configure`, and `drivers/pcie/host/controller.c`, `pcie_generic_ctrl_enumerate_type0`.
- **What is wrong**: 🎓 a PCIe function answers at the addresses in its BARs only once the *memory space* bit of its command register is set. On a PC the firmware sets it. Where Zephyr does the bus scan itself (`CONFIG_PCIE_CONTROLLER`), the scan gives each BAR an address and sets the bit for bridges only, and the NVMe driver goes straight on to read the drive's registers. Zephyr's other PCIe drivers set the bit themselves (`eth_e1000.c`, `uart_ns16550.c` and more, with `pcie_set_cmd(bdf, PCIE_CONF_CMDSTAT_MEM, true)`).
- **How to see it**: with the bit left clear, the driver's first read of the drive's registers gets a bus error on socpuppet's endpoint, and all ones on a real bus.
- **What we do**: after the scan, `socpuppet_pcie.c` sets the bit in every function on the bus, as the firmware of a PC would have.
- **Upstream fix**: one line in `nvme_controller_pcie_configure`, as the other drivers have. Setting it in the scan, for every function whose BARs were placed, would cover drivers yet to be written.
- **Kind**: bug.
- **When it lands**: delete `socpuppet_pcie_enable_memory_decoding`.

### The PCIe bus scan needs 3 KB of the interrupt stack, and runs off the end of it

- **Where**: `drivers/pcie/host/controller.c`, `pcie_generic_ctrl_enumerate`, the local `stack[MAX_TRAVERSE_STACK]`.
- **What is wrong**: the scan keeps its place in an array of 256 entries of 12 bytes on the stack. A controller driver runs it from its init function, before the kernel has threads, when the stack is the one interrupts use: `CONFIG_ISR_STACK_SIZE`, 2048 bytes unless the architecture says otherwise. Arm64 says otherwise, and RISC-V does not. The frame reaches past the end of the stack into whatever the linker put next. In our image that is a thread's stack that is not yet in use, so nothing shows.
- **How to see it**: disassemble the function in an image built with the default (its frame is over 3 KB), and look at what symbol comes before `z_interrupt_stacks`.
- **What we do**: the SoC's `Kconfig.defconfig` makes the default 8192 with `PCIE_CONTROLLER`.
- **Upstream fix**: make the array static, or size it with a Kconfig option that a board with one bus can set to 1.
- **Kind**: bug.
- **When it lands**: drop the default.

### The NVMe driver includes `soc.h` and uses nothing from it

- **Where**: `drivers/disk/nvme/nvme_controller.c`, `#include <soc.h>`.
- **What is wrong**: not every SoC has a `soc.h`. One with nothing to put in it, as ours is, cannot build the driver.
- **How to see it**: `fatal error: soc.h: No such file or directory`.
- **What we do**: an empty `soc/socpuppet/soc.h`.
- **Upstream fix**: drop the include.
- **Kind**: build.
- **When it lands**: delete the file, and the include directory in the SoC's `CMakeLists.txt`.

### A flash driver that asks its chip how big a page is cannot say so

- **Where**: `include/zephyr/drivers/flash.h`, `struct flash_parameters`, the member `const size_t write_block_size`.
- **What is wrong**: the comment above the structure says its values are "filled in during flash device initialization and stay constant through a runtime". The `const` on the member says something stronger: that they are known when the driver is compiled. A driver that learns the size from the device (🎓 a NAND chip says what it is when asked, with a command called Read Parameter Page) has a structure in its device data that C will not let it assign to.
- **How to see it**: in a driver's init function, `data->parameters.write_block_size = size_the_chip_gave;`. The compiler says `assignment of read-only member 'write_block_size'`. Assigning a whole structure fails the same way.
- **What we do**: `drivers/ssd/flash_controller.c` builds the structure as a compound literal and copies it over the one in the device data with `memcpy`. The object it copies over was not defined `const`, so that is allowed, and it is still a way round what the header asks for.
- **Upstream fix**: drop the `const` from the member. `get_parameters` already returns a pointer to a `const` structure, and that is what keeps a caller from writing to it.
- **Kind**: portability.
- **When it lands**: the `memcpy` becomes an assignment.

### A flash bigger than 2 GiB has no offsets on a 32-bit CPU

- **Where**: `include/zephyr/drivers/flash.h`: `flash_read`, `flash_write` and `flash_erase` take an `off_t`, and `struct flash_pages_info` holds one.
- **What is wrong**: `off_t` is the C library's, and with the SDK's library for 32-bit RISC-V it is a `long`, 32 bits and signed. The last byte the flash API can name is just short of 2 GiB. `flash_get_size` gives a `uint64_t`, so a driver can say how big its flash is and a caller still cannot reach the far end of it. An SSD's NAND is that big as a matter of course, and its controller is very often a 32-bit CPU.
- **How to see it**: `sizeof(off_t)` in an application for `socpuppet_ssd` is 4.
- **What we do**: the firmware refuses the drive. `firmware/ssd/src/ftl.c` compares the NAND's size with what an `off_t` can name before it makes its table, says both numbers on the console, and stops. `tests/python/test_ssd_zephyr_firmware.py` holds it to that, at 3 GiB and at exactly 2 GiB. 🎭 The Python stand-in for the firmware has no such limit, because it talks to the flash controller's registers, which count in pages.
- **Upstream fix**: a 64-bit offset type for the flash API. That is a large change with every flash driver in its path, so the proposal to make first is the question of whether the flash class is meant for raw NAND at all. Zephyr has no NAND class to use in its place.
- **Kind**: missing feature.
- **When it lands**: the firmware's check goes, and a drive may be bigger than 2 GiB. socpuppet keeps the flash class either way ([plan.md](plan.md), decided on 2026-10-09), so if the answer is that the class is not for raw NAND, the limit stays and this entry says so.

### `irq_enable` on RISC-V knows a PLIC's sources and not an IMSIC's identities

- **Where**: `soc/common/riscv-privileged/soc_common_irq.c`, `arch_irq_enable`, `arch_irq_disable` and `arch_irq_is_enabled`. And `drivers/interrupt_controller/intc_riscv_imsic.c`, which has `riscv_imsic_enable_eiid` and nothing that calls it.
- **What is wrong**: 🎓 a driver switches its interrupt on with `irq_enable(number)`, and the architecture decides what that means. On RISC-V it means a PLIC's source if there is a PLIC and the number is one of its, a CLIC's if there is a CLIC, and otherwise bit `number` of the hart's `mie` register. Zephyr's IMSIC driver takes a message's identity as the interrupt's number, so `irq_enable(32)` for an identity sets a bit of `mie` that has nothing to do with it (computed as `1 << 32` in an `int`, which is not defined), and the identity stays switched off in the IMSIC. Nothing in the tree connects the two. The file is compiled for every SoC with the privileged architecture, so a SoC cannot define the three again.
- **How to see it**: build `tests/drivers/disk/disk_access` for the host without the module's glue. The NVMe driver waits for the interrupt of its first command and Zephyr prints nothing at all. It was tried, once, by taking `--wrap` out of the module's build.
- **What we do**: `drivers/interrupt_controller/imsic_irq.c` in the module, and three `-Wl,--wrap=` options in its CMakeLists.txt, which send every call of the three to functions of ours: a number below 16 goes on to Zephyr's own, and one from 16 up is an identity, enabled in the IMSIC. `tests/python/test_zephyr_module.py` holds the numbers the board hands out to what the glue takes for an identity.
- **Upstream fix**: a third branch in `soc_common_irq.c`, under `CONFIG_RISCV_IMSIC`, that does this, as the CLIC and the PLIC each have one.
- **Kind**: missing feature.
- **When it lands**: `imsic_irq.c` and the three linker options go.

### The IMSIC driver turns its highest identity away, and enables the wrong register above 63

- **Where**: `drivers/interrupt_controller/intc_riscv_imsic.c`: `.nr_irqs = MIN(DT_INST_PROP(inst, riscv_num_ids), CONFIG_NUM_IRQS)` with `if (irq >= cfg->nr_irqs)` in `imsic_mext_isr`, and `eiid_to_eie_index`, `*reg_index = eiid / __riscv_xlen`.
- **What is wrong**: two things, both ⚠️ found by reading and neither run, since the host keeps clear of them. `riscv,num-ids` is the highest identity an IMSIC has, as the devicetree binding has it everywhere else (63, 127 and so on), and the handler treats it as one more than the highest: a message for identity 63 of a 63-identity IMSIC is reported as out of range. And on a 64-bit hart the registers of enable bits are numbered in twos, `eie0`, `eie2`, `eie4`, each of 64 bits, so identity N is in register `eie0 + 2 * (N / 64)`. The driver selects `eie0 + N / 64`, which for identities 64 to 127 is `eie1`: a register a 64-bit hart has not got, and an illegal instruction.
- **How to see it**: by reading. For the second, `irq_enable` on identity 64 with an IMSIC of 127 on RV64. socpuppet's model refuses the register, as the specification has it (`MessageControllerContract.AHartRegisterTheControllerHasNotIsRefused`).
- **What we do**: nothing in code. The host's IMSIC has 63 identities and hands out 32 and 33. `tests/python/test_zephyr_module.py` holds every identity the board gives a device to below the highest.
- **Upstream fix**: `irq > num_ids` for the first, and `2 * (eiid / 64)` when `__riscv_xlen` is 64 for the second.
- **Kind**: bug.
- **When it lands**: nothing to delete. The host could use identity 63, and an IMSIC of more than 63.

### Nothing sets an APLIC's source up, and `irq_enable` knows no APLIC either

- **Where**: `drivers/interrupt_controller/intc_riscv_aplic.c` and `intc_riscv_aplic_msi.c`, which have `riscv_aplic_config_src`, `riscv_aplic_msi_route` and `riscv_aplic_enable_src`, and `soc/common/riscv-privileged/soc_common_irq.c`, which calls none of them.
- **What is wrong**: 🎓 a device with an interrupt line at an APLIC needs three things done there before it can interrupt: its source given a mode, a target (which hart, and which identity to send), and its enable bit. The driver has a function for each and nothing in the tree calls them: no board has an APLIC node, and `irq_enable` does not know of one. A driver that does `IRQ_CONNECT` and `irq_enable` for a source of an APLIC, as the 16550's does, gets a bit set in `mie` and no interrupt, ever.
- **How to see it**: build `samples/subsys/shell/shell_module` for `socpuppet_host` with the call that sets the source up taken out of the module's glue. The shell never prompts, since it waits for an interrupt to transmit as well as to receive, and all six tests of `tests/python/test_m13_exit.py` fail. It was tried, once.
- **What we do**: the same file as for the IMSIC, `drivers/interrupt_controller/imsic_irq.c` in the module. A number that some device's node has as its interrupt at an APLIC is that source of that APLIC, and a board may have more than one APLIC: `irq_enable` gives it the mode "asks while its line is high", routes it to hart 0 as the identity of its own number, and enables it at the IMSIC and then at the APLIC, in that order, so that a line already asking is heard. So one number is the interrupt all the way, which is what Zephyr's flat table of interrupts wants. `tests/python/test_zephyr_module.py` holds the board's numbers to that.
- **Upstream fix**: with the branch for an IMSIC in `soc_common_irq.c` (the entry above), one for an APLIC's sources, and the mode taken from the interrupt's flags in the devicetree.
- **Kind**: missing feature.
- **When it lands**: the APLIC's part of `imsic_irq.c` goes.

### The APLIC driver sends a level once, and never looks again

- **Where**: `drivers/interrupt_controller/intc_riscv_imsic.c`, `imsic_mext_isr`, and the APLIC driver, which has nothing for it.
- **What is wrong**: 🎓 with an APLIC that delivers by message, a level-sensitive source is sent when its line rises, and its pending bit is cleared as the message goes. If the device is still asking when its handler returns, nothing rises, and no second message follows. The specification's answer is a register, `setipnum`: written with the source's number, it makes the source pending again if its line is still asking. Linux's driver writes it after every handler of a level-sensitive source. Zephyr's handler calls the device's routine and returns. A 16550 shows it at once: with a received byte waiting and room to transmit, its handler sees to one and the line stays high for the other. From then on the console neither hears nor speaks.
- **How to see it**: build the shell with the write of `setipnum_le` taken out of the module's glue. It prompts, and then is deaf: every test in `tests/python/test_m13_exit.py` that types fails, a single command among them, and not only the one that types while the shell is printing. It was tried, once.
- **What we do**: in the module's `imsic_irq.c`. When a source of the APLIC is enabled, its place in Zephyr's interrupt table is taken by a routine of the module's, with the driver's own behind it: it runs the driver's and then writes the source's number to `setipnum_le`. The table has to be one that can be written while the image runs, which is `CONFIG_DYNAMIC_INTERRUPTS`, and the module selects it when there is an APLIC. 💡 Zephyr's 16550 driver has an answer of its own for a controller that only hears edges, `CONFIG_UART_NS16550_WA_ISR_REENABLE_INTERRUPT`, which switches the UART's interrupts off and on again at the end of its handler. It was tried once in place of the module's write, and carried the exit test just as well. But it is for that one driver, and the next device with a wire would be deaf in the same way, so the module does it where the specification does, at the APLIC.
- **Upstream fix**: in `imsic_mext_isr`, after the routine, the write for an identity that an APLIC's level-sensitive source sends. Or a hook the APLIC driver can register.
- **Kind**: bug.
- **When it lands**: the routine and the saved handlers go.

### The APLIC driver never asks for delivery by message, and sets a bit the specification keeps

- **Where**: `drivers/interrupt_controller/intc_riscv_aplic.c`, `riscv_aplic_domain_enable` ("Do not modify DM bit"), and `intc_riscv_aplic_msi.c`, `riscv_aplic_msi_route` (`APLIC_TARGET_MSI_DEL`, bit 11).
- **What is wrong**: two things, by reading. 🎓 An APLIC that can deliver both ways comes out of reset delivering over a line, and firmware chooses messages by setting the DM bit of `domaincfg`. The driver in MSI mode sets IE and leaves DM as it finds it, so on such an APLIC it routes every source for messages and none is ever sent. And it sets bit 11 of every `target` it writes, calling it "MSI_DEL". The ratified specification has no such bit: with messages, bits 11 and 17 to 12 of `target` are the guest index or reserved.
- **How to see it**: by reading. `AplicContract.OutOfResetTheDomainDeliversByMessage` and `ABitTheSpecificationKeepsInATargetIsNotSent` in `tests/cpp/contracts/aplic_contract.h` are what socpuppet's APLIC does about each.
- **What we do**: nothing in firmware. socpuppet's APLIC delivers by message only, so its DM bit is one and cannot be cleared, which the specification allows, and it ignores bit 11.
- **Upstream fix**: set DM in `aplic_msi_init`, and drop bit 11.
- **Kind**: bug.
- **When it lands**: nothing to delete.

### Kconfig cannot see `interrupts-extended`, and the 16550 driver asks it whether the UART can interrupt

- **Where**: `drivers/serial/Kconfig.ns16550`, `select SERIAL_SUPPORT_INTERRUPT if $(dt_compat_any_has_prop,$(DT_COMPAT_NS16550),interrupts)`, and `scripts/dts/python-devicetree/src/devicetree/edtlib.py`, where a property of the type `compound` gets no `Property` object.
- **What is wrong**: 🎓 a devicetree node says where its interrupt goes with `interrupts` and an `interrupt-parent`, or with `interrupts-extended`, which names the controller in the same property. They mean the same, and Zephyr's C macros (`DT_IRQN` and the rest) read either. Kconfig's devicetree functions do not: `interrupts-extended` is declared `compound`, the library makes no object for a property of that type, and so `dt_compat_any_has_prop(..., interrupts-extended)` is never true and `(..., interrupts)` is true only of the first spelling. The 16550's Kconfig asks exactly that to decide whether the UART can interrupt. With the second spelling the answer is no, the shell falls back to polling the UART, and nothing says why. ⚠️ The machine timer's binding goes the other way and requires `interrupts-extended`, so a generator cannot pick one spelling for every node.
- **How to see it**: build `samples/subsys/shell/shell_module` for a board whose UART node has `interrupts-extended`. `CONFIG_SHELL_BACKEND_SERIAL_API_POLLING=y` is in the `.config`, and `TestWhenPythonTypesACommandAtTheHostsShell.test_what_was_typed_reached_the_cpu_as_messages_from_the_io_die` fails: the shell answers, and no interrupt was sent.
- **What we do**: a UART's node is generated with `interrupt-parent` and `interrupts` (`DeviceNode.short_interrupts` in `python/socpuppet/components.py`). Every other node keeps `interrupts-extended`.
- **Upstream fix**: have `dt_compat_any_has_prop` and its siblings answer for `interrupts` when the node has either spelling, or give the drivers a function that asks whether a node has an interrupt.
- **Kind**: bug.
- **When it lands**: `short_interrupts` can go, and every node can be written the same way.

## SPDK

[spdk/spdk](https://github.com/spdk/spdk), the Storage Performance Development Kit, pinned at `0bbb7fe4` ("v26.09") in `cmake/Dependencies.cmake`. socpuppet borrows one file from it, `include/spdk/nvme_spec.h`: the registers, commands and data structures of the NVMe specification as C structs. The NVMe controller's logic (`src/socpuppet/core/nvme_controller.cpp`) is ours.

### The NVMe definitions cannot be included without the rest of SPDK's environment

- **Where**: `include/spdk/nvme_spec.h`, lines 14 and 20: `#include "spdk/stdinc.h"` and `#include "spdk/assert.h"`.
- **What is wrong**: the header is pure definitions, and all it uses from outside is the fixed-width integer types, `bool` and a static assertion. `spdk/stdinc.h` gives it those by including some seventy system headers: sockets, `pthread`, `epoll`, `aio` and more. A project that wants only the NVMe structures has to take all of that, on a platform that has all of it.
- **How to see it**: compile a file that includes only `spdk/nvme_spec.h` with SPDK's `include` directory on the path, and count the headers the preprocessor opens.
- **What we do**: no patch. `cmake/shims/spdk/` holds stand-ins for the two headers: a `stdinc.h` with four standard includes, and an `assert.h` that defines `SPDK_STATIC_ASSERT` as `static_assert`. Only `nvme_spec.h` itself is fetched.
- **Upstream fix**: have `nvme_spec.h` include `<stdint.h>`, `<stdbool.h>` and `<stddef.h>` itself, so that it stands alone. Other projects copy this file for the same reason.
- **Kind**: portability.
- **When it lands**: delete `cmake/shims/spdk/stdinc.h`.

### The structure size checks do nothing in C++

- **Where**: `include/spdk/assert.h`, lines 19 to 31.
- **What is wrong**: `SPDK_STATIC_ASSERT` becomes `static_assert` only `#ifdef static_assert`, and otherwise expands to nothing. 🎓 In C, `static_assert` is a macro from `<assert.h>`. In C++ it is a keyword, which `#ifdef` cannot see. So every C++ file that includes `nvme_spec.h` loses the checks that each structure has the size the specification gives it, and nothing says so.
- **How to see it**: in a C++ file, after including `spdk/assert.h`, write `SPDK_STATIC_ASSERT(false, "never seen");`. It compiles.
- **What we do**: no patch. `cmake/shims/spdk/assert.h` stands in for the header and defines the macro as `static_assert` outright.
- **Upstream fix**: `#if defined(__cplusplus) || defined(static_assert)`.
- **Kind**: bug.
- **When it lands**: fetch SPDK's `assert.h` alongside `nvme_spec.h` and delete the stand-in.

## VCML

[machineware-gmbh/vcml](https://github.com/machineware-gmbh/vcml), tried at `v2026.10.02` in the ISS spike (its UART) and in the PCIe spike (its PCI endpoint, [pcie-spike.md](pcie-spike.md)). 💡 socpuppet does not use VCML today. These are written down because they are what a project meets when it borrows one of VCML's models, and each has a test in the PCIe spike that shows it. 🦜 The spike has been deleted; the last commit that holds `spikes/pcie/` is `e10359f`, and the paths below are from there.

### Its support library is fetched without a pin

- **Where**: `CMakeLists.txt` line 32, `find_github_repo(mwr "machineware-gmbh/mwr")`.
- **What is wrong**: it clones the head of mwr's default branch while CMake configures, so two builds of the same VCML release a week apart can differ. Three days after release `v2026.10.02`, an unpinned build already took a different mwr commit from the release's.
- **How to see it**: configure the same VCML tag on two different days and compare the mwr commits. A second symptom: the clone goes into VCML's build directory, and it fails with "destination path already exists" when that directory is there but CMake's cache is new. That is exactly what a CI job gets when it restores its fetched dependencies from a cache. `spikes/pcie/pin_probe/` shows each case.
- **What we do**: `spikes/pcie/Vcml.cmake` declares `mwr` itself with `FetchContent`, at a commit, before VCML is added. VCML then finds the target and skips its clone, and a restored cache still configures. Setting `MWR_HOME` works too. `MWR_TAG` does not help: it takes a tag name, and fails on a restored cache like no pin at all.
- **Upstream fix**: record the mwr commit in each VCML release, and do not clone into a directory that is already there.
- **Kind**: build.
- **When it lands**: the pre-declaration in `Vcml.cmake` can go.

### It switches off SystemC's version check for everything that links it

- **Where**: `CMakeLists.txt` line 259, `target_compile_definitions(vcml PUBLIC SC_DISABLE_API_VERSION_CHECK)`.
- **What is wrong**: the definition is `PUBLIC`, so it reaches every target that links VCML. 🎓 That check is how SystemC catches two parts of a program built with different C++ standards, and a project that links VCML loses it without asking.
- **How to see it**: read the compile commands of any target that links `vcml`.
- **What we do**: the spike's adapter links VCML `PRIVATE`, which keeps the definition inside the adapter's one source file.
- **Upstream fix**: make it `PRIVATE`, or an option.
- **Kind**: build.
- **When it lands**: nothing to delete here.

### A PCI endpoint hides its own MSI-X table

- **Where**: `src/vcml/models/pci/endpoint.cpp`, `endpoint::receive`.
- **What is wrong**: `pci::device` keeps the MSI-X table and its pending bits inside a BAR, and `pci::endpoint` forwards every access to a BAR out through `bar_out`, to the function. So the host can never read or program the table of an endpoint that puts it in a BAR it shares with the function's registers.
- **How to see it**: `VcmlAsIs.TheMsixTableInBar0BelongsToTheFunction` in `spikes/pcie/as_is_test.cpp`.
- **What we do**: the spike's adapter overrides `receive()` and sends the table's range back to the device.
- **Upstream fix**: in `endpoint::receive`, give `device::receive` the addresses that overlap the MSI-X table and pending bits first.
- **Kind**: bug.
- **When it lands**: the override in `spikes/pcie/vcml_parts.h` can go.

### A BAR does not say what kind it is until the first reset

- **Where**: `src/vcml/models/pci/device.cpp`, `pci_declare_bar()`.
- **What is wrong**: declaring a BAR does not update its register, and with the reset input stubbed no reset ever comes. Until something is written to it, a 64-bit BAR reads 0, where a host expects the type bits (4 for 64-bit). 💡 The borrowed timer and PLIC have the same trouble with registers before a reset.
- **How to see it**: `VcmlAsIs.Bar0DoesNotSayItIs64BitUntilSomethingIsWritten`.
- **What we do**: the spike's adapter calls `reset()` at the end of elaboration.
- **Upstream fix**: update the BAR register when it is declared, or reset at the start of simulation.
- **Kind**: bug.
- **When it lands**: the call can go.

### A debug access that the target leaves unanswered ends the process

- **Where**: `src/vcml/models/pci/endpoint.cpp` (`bar_out[n].send()`), and `tlm_host.cpp` line 43.
- **What is wrong**: 🎓 a debug access is one that takes no time and that a target may decline. A target that declines need not set a response status. VCML's `send()` then stops with "invalid out-bound transaction response status".
- **How to see it**: `VcmlAsIs.AbortsOnADebugReadTheFunctionDoesNotAnswer`.
- **What we do**: the spike's adapter answers such an access itself.
- **Upstream fix**: for a debug send, take the status from how many bytes were transferred, as `access()` already does.
- **Kind**: bug.
- **When it lands**: the adapter's check can go.

### The thread that loads the library is taken for the kernel's

- **Where**: `src/vcml/core/systemc.cpp`, `thread::id sysc_thread = std::this_thread::get_id()`.
- **What is wrong**: the thread is recorded when the library is loaded, and a transaction from any other thread stops the process. A program that loads the library on one thread and runs the simulation on another, which a Python program may, cannot run.
- **How to see it**: `VcmlAsIs.AbortsWhenTheKernelIsNotOnTheThreadThatLoadedIt`.
- **What we do**: the spike's adapter calls `vcml::set_sysc_thread()` at the start of simulation.
- **Upstream fix**: do that in VCML itself, at the start of simulation.
- **Kind**: limitation.
- **When it lands**: the call can go.

### An error is `abort()`

- **Where**: mwr, `include/mwr/core/report.h`, `MWR_ERROR`, which `VCML_ERROR` is.
- **What is wrong**: a failed check prints a backtrace to stderr and calls `abort()`. There is no switch. A model built on VCML cannot report an error as an exception, so inside a Python extension a neighbour's mistake (reusing a payload with a response status left on it, for one) ends the interpreter. There are about a hundred such checks in the files the PCI endpoint runs through.
- **How to see it**: the `VcmlDeathTest` tests in `spikes/pcie/endpoint_test.cpp`.
- **What we do**: nothing. It is the main reason the PCIe spike recommends against borrowing the endpoint.
- **Upstream fix**: an option to throw `mwr::report`, as `MWR_REPORT` does.
- **Kind**: missing feature.
- **When it lands**: VCML's models become usable from a host that must survive an error.

### Messages are held back by the wrong bit, and DMA by none

- **Where**: `src/vcml/models/pci/device.cpp`, `msix_interrupt` and `msi_interrupt`, which test `PCI_COMMAND_MMIO`.
- **What is wrong**: an endpoint may not start any access of its own until the host sets the bus-master bit in its command register. VCML sends MSI and MSI-X messages whenever memory decoding is on, and forwards DMA always.
- **How to see it**: `Msix.IsGatedByMemoryEnableAndNotByBusMasterEnable` and `Dma.IsNotHeldBackByBusMasterEnable` in `spikes/pcie/endpoint_test.cpp`.
- **What we do**: nothing.
- **Upstream fix**: test `PCI_COMMAND_BUS_MASTER`, for messages and for DMA.
- **Kind**: bug.
- **When it lands**: nothing to delete here.

## QBox

[qualcomm/qbox](https://github.com/qualcomm/qbox), which the NPU spike builds at `4d63017c` ("libqemu: Switch to version libqemu-v11.0-v0.15", 2026-09-24) in `spikes/npu/hexagon/build.sh`. Not part of socpuppet's build: it is QEMU underneath (GPL-2.0), so users build it from source in a container.

### The lock file pins a libqemu tag that is not published

- **Where**: `package-lock.cmake`, the `libqemu` entry, from commit `0e4bdfd1` ("Adjust for new libqemu", 2026-10-05) on.
- **What is wrong**: it pins `GIT_TAG libqemu-v11.0.50-v0.1`, and [qualcomm/qemu](https://github.com/qualcomm/qemu) has no such tag (its newest in that series is `libqemu-v11.0-v0.15`). A clean build from the head of `main` cannot fetch QEMU.
- **How to see it**: `cmake --preset gcc` at that commit ends with `fatal: invalid reference: libqemu-v11.0.50-v0.1`, before anything is compiled.
- **What we do**: build the commit before it, `4d63017c`, whose tag is there. The ISS spike's recipe (`spikes/iss/qbox/build.sh`) names a later commit and would fail the same way today.
- **Upstream fix**: publish the tag, or pin one that is published.
- **Kind**: build.
- **When it lands**: the two recipes can move to the head again.

### The Hexagon components do not compile as C++20

- **Where**: `qemu-components/cpu_hexagon/include/hexagon.h` line 103 and `qemu-components/hexagon_globalreg/include/hexagon_globalreg.h` line 68, `SCP_FATAL(())("Unrecognized Architecture Revision: " + dsp_arch)`.
- **What is wrong**: `SCP_FATAL` is `fmt::format` underneath, and from C++20 on fmt checks its format string at compile time, so a string built at run time is refused: `the value of 'dsp_arch' is not usable in a constant expression`. QBox builds itself as C++17 and never sees it; a program that links QBox with C++20 code (socpuppet is C++20, and SystemC only links with code built to the same standard) has to build QBox as C++20 too.
- **How to see it**: `cmake --preset gcc -DLIBQEMU_TARGETS=hexagon -DCMAKE_CXX_STANDARD=20`, then build `hexagon_globalreg`.
- **What we do**: `spikes/npu/hexagon/build.sh` rewrites both lines to `("Unrecognized Architecture Revision: {}", dsp_arch)` before configuring, as it does for the ISS spike's two C++20 patches.
- **Upstream fix**: the same two-word change; it is what the macro expects and it reads the same in C++17.
- **Kind**: portability.
- **When it lands**: the third `sed` in the recipe.
