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

[Minres/DBT-RISE-Core](https://github.com/Minres/DBT-RISE-Core), pinned at `29e97c0`. It is the engine under the CPU model. How each of these was found is in [iss-spike.md](iss-spike.md).

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

- **Where**: `src/iss/debugger/server.h`, `server<SESSION>::run_server`, lines 50 to 56.
- **What is wrong**: the server is a singleton. A second call logs "server already initialized" as fatal. So only one CPU in a process can have a debugger attached, whatever port each asks for. A platform with three CPUs and three firmware images wants three.
- **How to see it**: two `core_complex` instances in one simulation, each with a `gdb_server_port`.
- **What we do**: nothing yet. One debugger is enough until the milestone that runs two firmware images together (M6 in [plan.md](plan.md)).
- **Upstream fix**: one server per port, owned by the core that asked for it.
- **Kind**: missing feature.
- **When it lands**: several CPUs can each take a `gdb_port`.

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
- **What we do**: `cmake/patches/dbt-rise-riscv-interrupt-after-access.patch`. After a bus transaction, the thread yields for up to two delta cycles if anything is scheduled for the current time. One updates the signal and runs the method. Two does not rely on the kernel's order of evaluation. Only accesses that go over the bus pay for it, and memory reached by DMI does not. Measured speed on a loop was unchanged.
- **Upstream fix**: the patch covers the single-threaded quantum keeper, which is what socpuppet builds. The multi-threaded `exec_b_transport` needs the same inside its `execute_on_sysc` call. An alternative that needs no yield: read the interrupt inputs directly at the points where the core checks for pending interrupts.
- **Kind**: bug.
- **When it lands**: drop the patch.

### A core that goes to sleep does not let the clock catch up first

- **Where**: `src/sysc/core2sc_adapter.h`, `wait_until`, which is where `wfi` ends up.
- **What is wrong**: a core runs ahead of the simulation's clock by up to a quantum (temporal decoupling). When it executes `wfi` it waits for an event straight away, without first waiting out the time it is ahead by. So the simulation's clock stays behind what the core has done, by up to a quantum, for as long as the core sleeps. A platform that stops while its CPU sleeps reports a time that depends on the quantum. TLM-2.0's guidance for a temporally decoupled process is to synchronize before it waits for anything but time.
- **How to see it**: one core, a quantum of 50 µs, a program that writes once to a target which adds 3 µs to the access and then executes `wfi`. `sc_start()` returns with `sc_time_stamp()` at 0, not at 3 µs or later. socpuppet's scripted master is held to this by `WhenAScriptEndsAheadOfTheClock.TheClockCatchesUpBeforeTheRunEnds` in `tests/cpp/contracts/bus_master_test.cpp`. The CPU is not.
- **What we do**: nothing. The effect is bounded by the quantum.
- **Upstream fix**: synchronize the quantum keeper at the top of `wait_until`'s wait, after accounting for the cycles executed since the last sync.
- **Kind**: bug, or at least a surprise.
- **When it lands**: the test above can move into the contract that both masters pass.

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

### The ACLINT's and the PLIC's registers are indeterminate until reset is pulsed

- **Where**: `minres/gen/aclint_regs.h` and `rvi/gen/plic_regs.h`, the storage declarations (`uint64_t r_mtime;`, `std::array<uint32_t, ...> r_priority;` and the rest).
- **What is wrong**: the storage has no initial value, and the registers get their reset values only when `rst_i` moves. That is how hardware behaves, so it is defensible. But a platform that ties `rst_i` low, as one with no reset controller does, starts with whatever was in memory. With an ordinary allocator that is usually zero, which looks like it works.
- **How to see it**: build with AddressSanitizer, which fills new memory with a pattern, tie `rst_i` low and read `mtime` at time zero. In socpuppet, 15 tests failed in the sanitizer build and nowhere else.
- **What we do**: no patch. The adapters (`machine_timer.cpp`, `plic.cpp`) call `reset_start()` and `reset_stop()` on the registers as the simulation starts.
- **Upstream fix**: value-initialize the storage, or reset the registers in `start_of_simulation`.
- **Kind**: a surprise more than a bug.
- **When it lands**: the adapters can stop doing it.

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
