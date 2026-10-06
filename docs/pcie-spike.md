# The PCIe spike: borrow VCML's endpoint, or write our own?

This is the report of a time-boxed spike for milestone M2 in [plan.md](plan.md). It ends with a recommendation. Nothing has been decided, and nothing outside `spikes/pcie/` has been built on the answer.

**In one paragraph.** VCML's PCI model can be socpuppet's PCIe endpoint. It builds here with no patches, links statically into the Python extension for 1.1 MB, and behind an adapter it passes everything on the checklist, up to an NVMe Identify whose interrupt arrives as an MSI-X message, driven from Python. The recommendation is still to write our own. The half of VCML's model that socpuppet's design can use is small, the adapter that fits it in is at least two thirds the size of a hand-written endpoint, and VCML stops the whole process with `abort()` when a neighbour does something it does not expect.

## The question

🎓 A PCIe endpoint is the part of a device that the bus sees. It owns configuration space (who made the device and what it is), the base address registers (BARs, through which the host decides where the device's registers appear in memory) and the MSI-X table (where each interrupt is to be sent, as a small write into host memory). Behind it sits the function, here socpuppet's behavioral NVMe controller, which knows nothing about PCIe: it has a register block, a port for reading and writing host memory (DMA), and one interrupt line per vector.

[VCML](https://github.com/machineware-gmbh/vcml) (MachineWare, Apache-2.0) has such a model in two halves, `vcml::pci::host` and `vcml::pci::endpoint`, joined by a PCI socket of VCML's own. That socket cannot be a socpuppet port, be traced, or cross a die-to-die link. So borrowing means an adapter: VCML inside one source file, plain TLM sockets and wires outside.

## What was tried

Everything is in [spikes/pcie/](../spikes/pcie/README.md), on macOS (x86-64, Apple clang 21), against VCML and mwr release `v2026.10.02`.

- **Two adapters.** `VcmlEndpoint` puts VCML's host and endpoint together in one module. `VcmlBareEndpoint` borrows the endpoint alone and plays the host's part towards it. The second is the shape the M2 design needs: the root complex is a socpuppet component of its own, on the far side of a link made of plain TLM sockets, which leaves VCML's host nowhere to stand.
- **One set of 26 tests for both**, and two more for the first adapter alone, built on `Platform` with the behavioral NVMe function or 🎭 a stand-in function behind the endpoint, and a spy on everything the endpoint sends towards host memory.
- **Four more tests of VCML as it comes**, which pass while VCML misbehaves in the ways described below.
- **A copy of the Python extension** with the adapter, VCML and mwr linked in, a Python script that drives the whole path, and socpuppet's own 120 Python tests run on that extension.

## Answers

| # | Question | Answer | How |
|---|---|---|---|
| 1 | Can mwr be pinned from outside? | ✅ Yes. Declaring `mwr` with FetchContent at a commit before VCML is added makes VCML skip its own clone. `MWR_HOME` works too. Both survive a configure with only `_deps` kept, as a CI cache restore gives. `MWR_TAG` pins a tag name only and fails there with "destination path already exists", as does no pin at all. Left alone, VCML took the head of mwr, which three days after the release was already another commit. | measured |
| 2 | Does it build as C++20, static, against SystemC 3.0.2? | ✅ On macOS, with no patches and no warnings, in 2 min 12 s with ten jobs, SystemC included. Off: `VCML_USE_SDL2`, `SLIRP`, `TAP`, `LUA`, `SOCKETCAN`, `USB`, `VCML_BUILD_TESTS`, `VCML_BUILD_UTILS`, and `MWR_USE_LIBELF` (as a cache entry). The extension gains no shared library. | measured |
| 2 | On Linux, x86-64 and aarch64? | 🚧 The machine has no Docker. The ISS spike built the same release on Linux. | not tested |
| 3 | `main`, signal handlers, threads, output, a kernel kept busy? | ✅ None of them. `main` is in a library of its own that a program with a `main` never pulls in. No signal has a handler after a run and Python's SIGINT handler is untouched. No thread is started. Nothing is printed, and VCML's own log goes nowhere unless a publisher is made for it. An unbounded `sc_start()` returns. | measured |
| 3 | And when something goes wrong? | ❌ VCML's checks print a backtrace to stderr and call `abort()`. There is no switch: it is a macro in mwr. See below. | measured, read |
| 4 | Does it elaborate under `Platform::Elaborate()`? | ✅ Yes, inside a group as well. Loading the library creates one channel and one process in the kernel before any platform exists, which did no harm. | measured, read |
| 5 | Does `SC_DISABLE_API_VERSION_CHECK` stay in the adapter? | ✅ Yes. With VCML linked `PRIVATE`, the adapter's own source file has the definition and VCML's include paths. The test program that links the adapter has neither. | measured |
| 6 | Can the adapter show only plain TLM and wires? | ✅ Yes. VCML's TLM sockets are plain 32-bit sockets underneath and bind directly, and a wire goes in through VCML's `gpio_initiator_adapter`. DMA data is not copied. A configuration or BAR access is copied into VCML's PCI payload and back, eight bytes at most, and extensions on it do not travel. 256 lines with VCML's host, 366 without. | measured |
| 7a | IDs through ECAM, absent functions, class code | ✅ 00:00.0 answers with what it was given, class 01/08/02 included. Any other function reads all ones with no error. | measured |
| 7b | 64-bit BAR0 sized and placed as Zephyr does it | ✅ Once the endpoint has been reset (see below). Accesses reach the function at the right offset, and with memory decoding off they get an address error. No access to a BAR may be longer than eight bytes. | measured |
| 7c | A 4096-byte DMA write | ✅ One transaction. The eight-byte limit is for configuration and BARs only. Left alone, VCML then asks the memory for DMI and its later DMA never appears on the bus. The adapter switches that off. | measured |
| 7d | Capability list, MSI-X table, messages | ✅ MSI-X is found by walking the list. The table shares BAR0, after the function's 0x2000 bytes. Each rise of a line is exactly one 4-byte write of the vector's data to its address. A masked vector sets its pending bit and sends on unmasking. Disabled sends nothing. | measured |
| 7e | Which process sends, and who waits? | The messages come from an SC_THREAD of VCML's, `msix_process`, and DMA goes out in the thread that asked for it. VCML does `wait()` inside `b_transport`. See below. | measured |
| 7f | The whole path | ✅ The tests' `NvmeHost` enables the controller through the BAR window, Identify completes and its interrupt is one MSI-X message. Block writes read back. | measured |
| 8 | Into the Python extension | ✅ Imports in silence, starts no thread, and socpuppet's 120 Python tests pass on it. Release, stripped: 7.97 MB without VCML, 9.08 MB with (+1.11 MB, 14%). Zipped as a wheel would: 2.22 MB and 2.57 MB. | measured |
| 9 | Licences | ✅ VCML and mwr are Apache-2.0, every file MachineWare's, and with these options nothing else is linked. | read |
| 10 | Cost | 366 lines of adapter and 60 of CMake, against an estimated 450 to 550 for our own. See below. | measured, estimated |

## What the adapter has to put right

Four things, all in `spikes/pcie/vcml_parts.h` and the adapters, and each shown by a test in `as_is_test.cpp`.

- **The MSI-X table cannot be reached.** `pci::device` keeps the table inside a BAR, and `pci::endpoint` sends every access to a BAR out to the function. VCML's tests cover MSI-X on a device and not on an endpoint. The adapter overrides `receive()` to send the table's range back.
- **There is no power-on reset.** Until its reset line has pulsed, BAR0 reads 0 and does not say it is a 64-bit BAR, which is the first thing Zephyr reads. The adapter calls `reset()` at the end of elaboration. 💡 The borrowed timer and PLIC needed the same.
- **A debug read that the function leaves unanswered aborts.** A target may ignore a debug access, and ours do. VCML insists on a response status.
- **VCML takes the thread that loaded it for the kernel's thread**, and aborts on a transaction from any other. The adapter tells it as the simulation starts.

## What the adapter cannot put right

- ❌ **`abort()`.** Every `VCML_ERROR` prints a backtrace and ends the process: 100 of them in the files this endpoint runs through. From Python that is not an exception and not a parked failure. The interpreter is simply gone, and pytest reports a crashed worker. Two that the adapter leaves reachable were measured: a transaction that arrives at VCML's host with a response status left over from its last use, and DMA from an SC_METHOD. By reading, the endpoint's DMA socket makes the first check too.
- ⚠️ **Time.** VCML keeps its own account of how far each process has run ahead. The caller's annotated delay does not reach the function (it sees zero), and the function's does not come back. With socpuppet's default quantum of zero, every BAR access waits two delta cycles inside `b_transport`, and a function that says an access takes 7 ns makes VCML wait 7 ns there. With a quantum of 1 µs the BAR accesses wait for nothing. Some configuration registers always wait one delta.
- ⚠️ **Bus mastering.** A real endpoint sends nothing until the host sets the bus-master bit. VCML sends MSI-X messages when memory decoding is on, and forwards DMA always.
- ⚠️ **No test without the kernel.** socpuppet keeps a model's logic in plain C++ so that most tests need no simulator. VCML's endpoint is an `sc_module` through and through, so each of its tests is a process.

## What surprised

- How little there was to fight. The first build of the first adapter passed 23 of its first 25 tests.
- That VCML's endpoint and its MSI-X table had never met. By reading, VCML's own xHCI controller on PCI declares its table the same way and has the same problem.
- That the other session's build reformatted the spike's files while they were being written. 💡 The lint check covers untracked files too, so a spike has to be lint-clean from its first save.

## Cost

| | Lines | Notes |
|---|---|---|
| Adapter with VCML's host | 256 (157 of code) | Not the shape the design needs. |
| Adapter with the endpoint alone | 366 (263 of code) | It does the root complex's decoding of configuration and memory accesses itself, and the DMA and message sending. |
| CMake | about 60 | The recipe and one library. |
| Patches | none | One to mwr would be needed to turn `abort()` into an exception. |
| What comes along | 91,600 lines, 1.11 MB | All of VCML and mwr are compiled. `pci/device` and `pci/endpoint`, the part used, are 1,270. |
| Our own, estimated | 450 to 550 | A plain C++ core (configuration header, one 64-bit BAR, the capability list, the MSI-X table and pending bits, edge to message) of about 300, a header of 80, and a SystemC wrapper of about 120. The behavioral NVMe controller, which does more, is about 800 in all. |

🎓 What a reader of the adapter has to learn about VCML first: its PCI payload and address spaces, how a socket finds its owner by searching the module hierarchy (which is why the adapter's inside has to be a VCML module), stubbing of clocks and resets, the GPIO adapter, the sideband that marks a debug access, the chain of `receive()` overrides, register synchronisation, and that an error is an `abort()`.

## Recommendation

**Write our own endpoint, with VCML's `pci/device.cpp` open on the desk.** Three facts decide it.

1. **The borrowable part is small.** The root complex is ours either way, so VCML's host is out and what is left to borrow is about 1,270 lines, of which the adapter replaces the decoding. The saving is perhaps 150 lines of transcribing the specification's tables, for 366 lines of adapter that a learner cannot read without learning VCML.
2. **`abort()` is not negotiable from outside.** Everything else VCML gets wrong the adapter can correct. That one needs a patch to mwr and a careful read of a hundred call sites, and until then a model next to the endpoint can end a Python session by reusing a payload.
3. **It would be the one model with a different idea of time**, and the one model with no kernel-free tests.

What the spike leaves behind is worth keeping whichever way the decision goes. `endpoint_test.cpp` talks to the endpoint only through its ports, so it is most of a contract suite for the endpoint, and it already passes on two implementations. The recipe in `Vcml.cmake` pins VCML properly, should a later model be worth borrowing.

💡 If the decision is to borrow after all, take the second adapter, patch mwr's error macro to throw, and send the MSI-X fix upstream first.

## Not exercised

- Linux, on either architecture.
- Zephyr's own PCIe and NVMe drivers. The sizing sequence was copied from `drivers/pcie/host/pcie.c` by hand.
- A BAR placed above 4 GiB, more than one function, legacy interrupts and MSI (as opposed to MSI-X).
- DMI through a BAR, a traced connection to the endpoint, and a quantum other than zero and 1 µs.
- What `abort()` looks like from Python. It was measured in C++ only.

## For docs/upstream.md

📮 Four entries for VCML, none sent: the endpoint that hides its own MSI-X table, the debug access that must be answered, the BAR that does not show its type before the first reset, and `MWR_TAG` failing on a restored build directory (which the existing entry about the unpinned clone already half describes, and which now has a workaround).

## Decisions

Decided on 2026-10-05: **socpuppet writes its own PCIe endpoint.** It is a plain C++ core with a thin SystemC wrapper, like the NVMe controller, and it is built test-first in the main tree. The spike's code stays in `spikes/pcie/` as the record of what VCML does, and nothing builds it.
