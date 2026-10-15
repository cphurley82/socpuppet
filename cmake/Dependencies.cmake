# Third-party dependencies, pinned. Everything is built from source as a
# static library so one binary holds exactly one SystemC kernel.
include(FetchContent)

# EXCLUDE_FROM_ALL keeps a dependency's install rules out of our wheel.
# SYSTEM silences warnings from its headers.

# --- SystemC, ours or QBox's -------------------------------------------------
# QBox (Qualcomm's QEMU in SystemC) is a second CPU, built from source by
# tools/build_qbox.sh because QEMU is GPL. Its libraries link a shared
# SystemC and CCI of their own, and one process can hold only one SystemC
# kernel, so a build with QBox links socpuppet to those same two libraries.
# Without QBox, SystemC is fetched at the commit QBox builds and linked
# statically, as always, so the two builds run the same kernel.
set(SOCPUPPET_QBOX_DIR "" CACHE PATH
  "A QBox install made by tools/build_qbox.sh, to build the qbox_cpu with")
if(SOCPUPPET_QBOX_DIR)
  if(NOT EXISTS ${SOCPUPPET_QBOX_DIR}/lib/cmake/qbox-2.0/qboxConfig.cmake)
    message(FATAL_ERROR "SOCPUPPET_QBOX_DIR is \"${SOCPUPPET_QBOX_DIR}\", "
      "and there is no QBox installed there. Build it with "
      "tools/build_qbox.sh, which installs it in build/qbox/install.")
  endif()
  list(APPEND CMAKE_PREFIX_PATH ${SOCPUPPET_QBOX_DIR})
  # CMake keeps where it found each package, and looks there first next
  # time. A tree pointed at another install has to forget all of them.
  if(NOT SOCPUPPET_QBOX_DIR STREQUAL _SOCPUPPET_QBOX_DIR_FOUND)
    foreach(_package SystemCLanguage SystemCCCI qbox reporting libqemu)
      unset(${_package}_DIR CACHE)
    endforeach()
    set(_SOCPUPPET_QBOX_DIR_FOUND ${SOCPUPPET_QBOX_DIR} CACHE INTERNAL
      "The QBox install the packages below were found in")
  endif()
  find_package(SystemCLanguage CONFIG REQUIRED)
  find_package(SystemCCCI CONFIG REQUIRED)
  # QBox installs SystemC's headers in one directory with its own copies of
  # fmt and of a header called scp/report.h, both of which socpuppet has
  # newer or different ones of. A directory that holds SystemC's and CCI's
  # headers and nothing else keeps those two out of every file but the
  # QBox adapter's.
  set(SOCPUPPET_SYSTEMC_INCLUDE_DIR ${CMAKE_BINARY_DIR}/qbox-systemc/include)
  file(MAKE_DIRECTORY ${SOCPUPPET_SYSTEMC_INCLUDE_DIR})
  foreach(_header systemc systemc.h sysc tlm tlm.h tlm_core tlm_utils
      cci cci_configuration cci_inspection)
    file(CREATE_LINK ${SOCPUPPET_QBOX_DIR}/include/${_header}
      ${SOCPUPPET_SYSTEMC_INCLUDE_DIR}/${_header} SYMBOLIC)
  endforeach()
  set_target_properties(SystemC::systemc SystemC::cci-config
    SystemC::cci-inspection PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES ${SOCPUPPET_SYSTEMC_INCLUDE_DIR})
  set(SOCPUPPET_HAS_QBOX TRUE)
  message(STATUS "socpuppet: QBox from ${SOCPUPPET_QBOX_DIR}, with its "
    "SystemC ${SystemCLanguage_VERSION}")
else()
  FetchContent_Declare(systemc
    # The commit QBox builds, after 3.0.2 (tools/build_qbox.sh).
    GIT_REPOSITORY https://github.com/accellera-official/systemc.git
    GIT_TAG febde7a3e007ce3030cf574a4cb6fcc13d0ed820
    EXCLUDE_FROM_ALL SYSTEM)
  FetchContent_MakeAvailable(systemc)
  set(SOCPUPPET_SYSTEMC_INCLUDE_DIR ${systemc_SOURCE_DIR}/src)
  set(SOCPUPPET_HAS_QBOX FALSE)
endif()

if(SOCPUPPET_BUILD_TESTS)
  set(INSTALL_GTEST OFF)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.18.0.tar.gz
    URL_HASH SHA256=6e3191c1455468b3fc35a417fb565c1c5071aee1b7e7f85e30cf48a98d37d8b5
    EXCLUDE_FROM_ALL SYSTEM)
  FetchContent_MakeAvailable(googletest)
endif()

# The interpreter that builds the extension is also the one that runs pytest.
# Under `uv run`, this finds the project's virtual environment.
find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
set(PYBIND11_FINDPYTHON ON)
FetchContent_Declare(pybind11
  URL https://github.com/pybind/pybind11/archive/refs/tags/v3.1.0.tar.gz
  URL_HASH SHA256=ef712655692a2e9bf7bb7874c022564a45f91d847ddee987e720cd9e28849665
  EXCLUDE_FROM_ALL SYSTEM)

FetchContent_MakeAvailable(pybind11)

# --- SCC (SystemC-Components) and what it needs -----------------------------
# SCC looks its dependencies up with find_package(). OVERRIDE_FIND_PACKAGE
# makes those calls resolve to the copies fetched here, so nothing has to be
# installed on the machine.

# The Boost libraries whose headers DBT-RISE includes: its interpreter is
# built on coroutines, its GDB server on asio and threads, and its
# debugger's command parser on spirit.
set(_dbt_rise_boost
  asio bind coroutine2 foreach fusion lexical_cast optional phoenix
  serialization smart_ptr spirit thread tokenizer tuple variant)
# SCC needs the first two. DBT-RISE needs its list, and looks three more up
# with find_package.
set(BOOST_INCLUDE_LIBRARIES date_time filesystem
  ${_dbt_rise_boost} context coroutine program_options)
FetchContent_Declare(Boost
  URL https://github.com/boostorg/boost/releases/download/boost-1.89.0/boost-1.89.0-cmake.tar.xz
  URL_HASH SHA256=67acec02d0d118b5de9eb441f5fb707b3a1cdd884be00ca24b9a73c995511f74
  EXCLUDE_FROM_ALL SYSTEM OVERRIDE_FIND_PACKAGE)

FetchContent_Declare(fmt
  URL https://github.com/fmtlib/fmt/archive/refs/tags/12.0.0.tar.gz
  URL_HASH SHA256=aa3e8fbb6a0066c03454434add1f1fc23299e85758ceec0d7d2d974431481e40
  EXCLUDE_FROM_ALL SYSTEM OVERRIDE_FIND_PACKAGE)

set(SPDLOG_FMT_EXTERNAL ON)
FetchContent_Declare(spdlog
  URL https://github.com/gabime/spdlog/archive/refs/tags/v1.16.0.tar.gz
  URL_HASH SHA256=8741753e488a78dd0d0024c980e1fb5b5c85888447e309d9cb9d949bdb52aa3e
  EXCLUDE_FROM_ALL SYSTEM OVERRIDE_FIND_PACKAGE)

set(YAML_CPP_BUILD_TOOLS OFF)
# yaml-cpp 0.8.0 declares a minimum CMake older than CMake 4 accepts.
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)
FetchContent_Declare(yaml-cpp
  URL https://github.com/jbeder/yaml-cpp/archive/refs/tags/0.8.0.tar.gz
  URL_HASH SHA256=fbe74bbdcee21d656715688706da3c8becfd946d92cd44705cc6098bb23b3a16
  EXCLUDE_FROM_ALL SYSTEM OVERRIDE_FIND_PACKAGE)

FetchContent_MakeAvailable(Boost fmt spdlog yaml-cpp)
# Only yaml-cpp needed that. Whatever comes after says for itself which
# CMake it was written for.
unset(CMAKE_POLICY_VERSION_MINIMUM)

# QBox's package names the fmt it was built with, and finds ours (the
# OVERRIDE_FIND_PACKAGE above). Its libraries keep using their own, a
# shared fmt 9 whose names are in a namespace of their own (fmt::v9).
if(SOCPUPPET_HAS_QBOX)
  find_package(qbox CONFIG REQUIRED)
  # What a file that includes QBox's headers is compiled and linked with.
  # QBox's include directory comes first: it holds QBox's fmt and its
  # scp/report.h, which have to win over socpuppet's fmt and SCC's
  # (docs/upstream.md). QBox's headers instantiate fmt 9 with names from
  # its shared library, which nothing of QBox's passes on. Its CPUs are
  # plug-ins, with their headers beside them.
  find_library(_qbox_fmt NAMES fmt PATHS ${SOCPUPPET_QBOX_DIR}/lib
    NO_DEFAULT_PATH NO_CACHE REQUIRED)
  add_library(socpuppet_qbox INTERFACE)
  target_include_directories(socpuppet_qbox SYSTEM INTERFACE
    ${SOCPUPPET_QBOX_DIR}/include
    ${SOCPUPPET_QBOX_DIR}/qemu-components/cpu_riscv/cpu_riscv64/include)
  target_compile_definitions(socpuppet_qbox INTERFACE FMT_SHARED)
  target_link_libraries(socpuppet_qbox INTERFACE ${_qbox_fmt} qbox::qbox)
endif()

# SCC probes for SystemC by compiling against an installed copy. Ours is
# built in this same tree, so tell SCC it is already found.
set(SystemC_FOUND TRUE)
set(SystemC_LIBRARIES SystemC::systemc)
# And the same for QBox's CCI, which SCC then uses in place of the copy it
# carries.
if(SOCPUPPET_HAS_QBOX)
  set(CCI_FOUND TRUE)
  set(CCI_LIBRARIES SystemC::cci)
endif()
# SCC's optional dependencies would be picked up from the machine if present
# and end up as shared-library dependencies of the wheel. Keep them out.
# zlib is the exception: SCC's bundled FST trace writer requires it, and it
# is part of every platform we target (the macOS SDK, the manylinux baseline).
foreach(optional BZip2 zstd LibLZMA lz4 elfio Catch2 flatbuffers PkgConfig)
  set(CMAKE_DISABLE_FIND_PACKAGE_${optional} TRUE)
endforeach()
set(BUILD_SCC_LIB_ONLY ON)
# SCP-style logging macros (SCP_INFO, ...) on top of SCC's logging backend.
set(WITH_SCP4SCC ON)
include(GNUInstallDirs)
# A git checkout rather than a tarball, because SCC carries git submodules.
FetchContent_Declare(scc
  GIT_REPOSITORY https://github.com/Minres/SystemC-Components.git
  GIT_TAG 42a9843e55efe92dfa44676afc7b372192ac1132 # 2026.07
  # SCC probes SystemC with try_compile, which cannot link a target built in
  # this same tree. The first patch points the probe at SystemC's headers
  # instead.
  #
  # The second is for clang-tidy. SCC bundles CCI, whose map element
  # references convert implicitly from void* through a protected constructor.
  # GCC 13's standard library asks about that conversion while it classifies
  # CCI's iterators, and clang reports the protected constructor as an error
  # where GCC only takes it for a "no". The patch makes the constructors
  # explicit, so the question is never asked.
  PATCH_COMMAND git apply
    ${CMAKE_CURRENT_LIST_DIR}/patches/scc-in-tree-systemc.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/scc-cci-explicit-elem-ref.patch
  UPDATE_DISCONNECTED TRUE
  EXCLUDE_FROM_ALL SYSTEM)
# SCC's install(EXPORT) rules demand that every dependency be installable
# too. We never install SCC (it is linked statically into our own binary), so
# its install() calls are switched off while it is being added.
function(install)
  if(NOT SOCPUPPET_SUPPRESS_INSTALL)
    _install(${ARGV})
  endif()
endfunction()
set(SOCPUPPET_SUPPRESS_INSTALL TRUE)
FetchContent_MakeAvailable(scc)
set(SOCPUPPET_SUPPRESS_INSTALL FALSE)
# SCC includes <boost/filesystem.hpp> but relies on a system-wide Boost to
# put it on the include path. With a fetched Boost it has to be linked.
target_link_libraries(scc-sysc PUBLIC Boost::filesystem)

# --- DBT-RISE-RISCV (Minres, BSD-3-Clause): the CPU model --------------------
# An instruction-set simulator with a SystemC wrapper, built by its own
# CMakeLists as an interpreter only. Its three translating backends stay
# off: TinyCC is LGPL, and asmjit and LLVM would each be one more dependency.
# Every patch and accommodation below is written up in docs/upstream.md.
# ELFIO reads ELF files. DBT-RISE asks for it, and socpuppet's own image
# loader (core/elf_image.cpp) uses it directly.
FetchContent_Declare(elfio
  URL https://github.com/serge1/ELFIO/archive/refs/tags/Release_3.12.tar.gz
  URL_HASH SHA256=e4ebc9ce3d6916461bc3e7765bb45e6210f0a9b93978bf91e59b05388c024489
  EXCLUDE_FROM_ALL SYSTEM)
# Which of DBT-RISE's translating backends are built besides its
# interpreter, and the backend a "dbt_rise_cpu" runs with when nothing says.
# None, and the interpreter, by default: that is what the wheel ships. M26
# measured the others (docs/plan.md). TinyCC is not offered: it has no core
# socpuppet could use, and it is LGPL.
set(SOCPUPPET_DBT_RISE_BACKENDS "" CACHE STRING
  "DBT-RISE's translating backends to build besides its interpreter: asmjit, llvm")
set(SOCPUPPET_DBT_RISE_DEFAULT_BACKEND interp CACHE STRING
  "The backend a dbt_rise_cpu runs with: interp, or one of those built")
foreach(_backend IN LISTS SOCPUPPET_DBT_RISE_BACKENDS)
  if(NOT _backend MATCHES "^(asmjit|llvm)$")
    message(FATAL_ERROR "SOCPUPPET_DBT_RISE_BACKENDS names \"${_backend}\", "
      "and the translating backends socpuppet can build are asmjit and llvm.")
  endif()
endforeach()
set(_dbt_rise_backends interp ${SOCPUPPET_DBT_RISE_BACKENDS})
if(NOT SOCPUPPET_DBT_RISE_DEFAULT_BACKEND IN_LIST _dbt_rise_backends)
  list(JOIN _dbt_rise_backends ", " _dbt_rise_backends_named)
  message(FATAL_ERROR "SOCPUPPET_DBT_RISE_DEFAULT_BACKEND is "
    "\"${SOCPUPPET_DBT_RISE_DEFAULT_BACKEND}\", and this build has "
    "${_dbt_rise_backends_named}. Add it to SOCPUPPET_DBT_RISE_BACKENDS.")
endif()
# How many of DBT-RISE's generated files are compiled at once (below).
set(SOCPUPPET_DBT_RISE_JOBS 4 CACHE STRING
  "How many of DBT-RISE's largest files to compile at once")
# asmjit (zlib licence) makes x86-64 code at run time, and so does DBT-RISE's
# backend built on it: it builds and runs on an x86-64 host only. At the
# commit DBT-RISE's own Conan recipe names (asmjit/cci.20240531).
if("asmjit" IN_LIST SOCPUPPET_DBT_RISE_BACKENDS)
  FetchContent_Declare(asmjit
    URL https://github.com/asmjit/asmjit/archive/d6c5be2212b9a50ba56ec6d1e9b68693c62136c1.zip
    URL_HASH SHA256=678549712d4708d0513fb0017d03211df415387aea4c031923d4dd5c07b43db6
    EXCLUDE_FROM_ALL SYSTEM OVERRIDE_FIND_PACKAGE)
  set(ASMJIT_STATIC ON)
  set(SOCPUPPET_SUPPRESS_INSTALL TRUE)
  FetchContent_MakeAvailable(asmjit)
  set(SOCPUPPET_SUPPRESS_INSTALL FALSE)
  set(WITH_ASMJIT ON)
else()
  set(WITH_ASMJIT OFF)
endif()
# LLVM (Apache-2.0 with LLVM exceptions) compiles for the host it runs on,
# so its backend builds wherever an LLVM development package is installed:
# Debian's llvm-19-dev (/usr/lib/llvm-19/lib/cmake/llvm) or Homebrew's llvm
# ($(brew --prefix llvm)/lib/cmake/llvm). DBT-RISE is written against
# LLVM 19. DBT-RISE-Core links a target that only DBT-RISE-RISCV's own
# WITH_SYSTEM_LLVM makes, from a path written into it, so it is made here
# from the package that was found, linked to its one shared library.
if("llvm" IN_LIST SOCPUPPET_DBT_RISE_BACKENDS)
  set(SOCPUPPET_LLVM_DIR "" CACHE PATH
    "The directory with LLVM's LLVMConfig.cmake, for the llvm backend")
  # Debian's LLVM package looks for libedit with pkg_check_modules and
  # never loads the module that defines it (docs/upstream.md). Included,
  # and not found: find_package(PkgConfig) goes to the provider here.
  include(FindPkgConfig)
  find_package(LLVM REQUIRED CONFIG HINTS ${SOCPUPPET_LLVM_DIR})
  message(STATUS "socpuppet: DBT-RISE's llvm backend, against LLVM "
    "${LLVM_PACKAGE_VERSION} in ${LLVM_DIR}")
  add_library(llvm-core::llvm-core INTERFACE IMPORTED GLOBAL)
  target_include_directories(llvm-core::llvm-core SYSTEM INTERFACE
    ${LLVM_INCLUDE_DIRS})
  separate_arguments(_llvm_definitions NATIVE_COMMAND "${LLVM_DEFINITIONS}")
  target_compile_definitions(llvm-core::llvm-core INTERFACE
    ${_llvm_definitions})
  target_link_libraries(llvm-core::llvm-core INTERFACE LLVM)
  set(WITH_LLVM ON)
else()
  set(WITH_LLVM OFF)
endif()
set(WITH_TCC OFF)
# No cores with the vector extension. Its helper library, softvector, is
# still built and linked: DBT-RISE asks for it either way.
set(DBT_RISE_RISCV_ENABLE_VECTOR OFF)
# DBT-RISE's own switch for pulling its fetched projects again on every
# configure. They are pinned here.
set(UPDATE_EXTERNAL_PROJECT OFF)
FetchContent_Declare(dbt_rise_riscv
  GIT_REPOSITORY https://github.com/Minres/DBT-RISE-RISCV.git
  GIT_TAG 2ad322399bc367db6b45f76ec3d7150d8dadeae6 # 2026-09-24
  GIT_SUBMODULES softvector
  # offsetof: Clang rejects the qualified member names in the generated
  # register tables. reset-restart: raising reset on a running core stopped
  # the simulation instead of restarting the core. static-library: the
  # library was SHARED whatever the build asked for, and one binary must
  # hold the one SystemC kernel. dmi-invalidate: a memory taking back direct
  # access to more than the one region it had granted was ignored.
  # interrupt-after-access: a handler that quieted its device was entered
  # again and again, because the core had not yet heard the line drop.
  # gdb-server-per-core: every core hung its `sysc` debugger command on the
  # first core's GDB server, where each now has a server of its own.
  # supervisor-interrupts: a core with supervisor mode could not enable an
  # interrupt handed down to that mode, so it never took one.
  # interrupt-drops-instruction: the same cores dropped a load, a CSR read
  # or an atomic that an interrupt arrived at. reset-pulse: a reset that
  # rose and fell while a busy core was ahead of the clock stopped the
  # simulation, where it now restarts the core. mip-read-only: firmware
  # could clear the pending bit of the machine timer's interrupt or of the
  # machine external one, and the core then slept through an interrupt whose
  # line stayed high. translate-fetches: with paging on, an instruction was
  # fetched from its virtual address as if that were a physical one, where
  # data was translated, and one that lay across two pages got its second
  # half from the first page again. fetch-ends-page: a two-byte instruction
  # that ended a page took a page fault for the page after, which it had
  # no use for. satp-warl: `satp` kept an address-space identifier that the
  # MMU then ignored, read as whatever was in memory until it was written,
  # and ended the process when written with a mode the MMU has not got. It
  # also takes Sv48 and Sv57 away, which is ours: no test here runs them.
  # tlb-dirty: a store to a page not marked dirty went through if a load
  # had been there first, where it is a page fault. xret-privilege: user
  # mode could execute `sret` or `mret` and land in whatever mode a
  # register said. sfence-user-mode: and `sfence.vma`.
  # interrupt-inside-exception: an interrupt that was pending when an
  # exception was taken was taken one instruction into the exception's
  # handler, whatever mode that was in and whatever it had masked, on the
  # cores with supervisor mode and on the ones without.
  # sret-tsr: the illegal instruction that `sret` is under `mstatus.TSR`
  # was raised and then thrown away. mprv-on-return: `mstatus.MPRV` stayed
  # set across a return to a mode below machine mode. counter-enables:
  # `mcounteren` and `scounteren` kept nothing and refused nothing, so
  # every mode could read every counter. sstatus-view: `sstatus` hid the
  # state of the floating-point registers from supervisor mode, and let it
  # set four bits that are machine mode's alone. fp-status: no instruction
  # looked at `mstatus.FS`, so floating point was never off and its state
  # never dirty. flw-address: `flw` and `fsw` cut their address to 32 bits.
  # one-reservation: a hart kept a reservation for every address it had
  # loaded reserved, and a store-conditional gave up only its own address's.
  # misaligned-amo: an atomic at a misaligned address raised a load's cause.
  # jit-wait-name: the translating backends call a helper named wait(),
  # which POSIX has taken (with DBT-RISE-Core's patch of the same name).
  # int128-traits: the translating backends' cores specialized a private
  # template of GCC's standard library, as DBT-RISE-Core's did.
  # asmjit-wfi-call: asmjit's `wfi` called the helper with a 1 where the
  # core's own pointer goes, and the process crashed at the first `wfi`.
  # llvm-core-names: the LLVM backend's 64-bit core was registered under a
  # name the SystemC wrapper never looks up. llvm-init-jit: and nothing in
  # the wrapper set up LLVM's target for the host, which riscv-sim's main()
  # does. llvm-wfi-call: LLVM's `wfi` called the helper as asmjit's did.
  PATCH_COMMAND git apply
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-offsetof.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-reset-restart.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-static-library.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-dmi-invalidate.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-interrupt-after-access.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-gdb-server-per-core.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-supervisor-interrupts.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-interrupt-drops-instruction.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-reset-pulse.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-mip-read-only.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-translate-fetches.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-fetch-ends-page.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-satp-warl.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-tlb-dirty.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-xret-privilege.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-sfence-user-mode.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-interrupt-inside-exception.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-sret-tsr.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-mprv-on-return.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-counter-enables.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-sstatus-view.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-fp-status.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-flw-address.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-one-reservation.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-misaligned-amo.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-jit-wait-name.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-int128-traits.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-asmjit-wfi-call.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-llvm-core-names.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-llvm-init-jit.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-llvm-wfi-call.patch
  UPDATE_DISCONNECTED TRUE
  EXCLUDE_FROM_ALL SYSTEM)
# DBT-RISE-RISCV fetches its core library itself, under this name and at
# this commit. Declaring it here first is how the patches get applied.
# ⚠️ The commit has to be the one DBT-RISE-RISCV's own CMakeLists.txt names
# (its FetchContent_Declare of dbt_rise_core_git): this declaration wins,
# so a newer DBT-RISE-RISCV would be built against an old core without a
# word. Checked against the pin above on 2026-10-07. Check again when
# that pin moves.
FetchContent_Declare(dbt_rise_core_git
  GIT_REPOSITORY https://github.com/Minres/DBT-RISE-Core.git
  GIT_TAG 29e97c021c988370f5c5af5b5076afe8043402b6
  # asio-names: Boost 1.87 removed the names its GDB server used.
  # int128-traits: it specialized a private template of GCC's standard
  # library, which Clang's library does not have. gdb-server-per-core: one
  # GDB server for the whole process, where each core that asks now gets
  # one on a port of its own. gdb-continue-answered-once: the server
  # answered one `continue` twice, and the second answer, written to a
  # debugger that had hung up, ended the process. gdb-rude-hangup: so did
  # a debugger whose connection was reset, which is what closing it with
  # an answer unread does. jit-wait-name: the translating backends' helper
  # was called wait(), which POSIX has taken, and on macOS the two collide.
  # llvm-pointer-args: LLVM's code took the core's pointers as bytes, so a
  # helper was handed the low eight bits of one.
  PATCH_COMMAND git apply
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-asio-names.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-int128-traits.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-gdb-server-per-core.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-gdb-continue-answered-once.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-gdb-rude-hangup.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-jit-wait-name.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-llvm-pointer-args.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-llvm-global-string.patch
  UPDATE_DISCONNECTED TRUE
  EXCLUDE_FROM_ALL SYSTEM)
set(SOCPUPPET_SUPPRESS_INSTALL TRUE)
FetchContent_MakeAvailable(elfio dbt_rise_riscv)
set(SOCPUPPET_SUPPRESS_INSTALL FALSE)
# A system-wide Boost keeps every header in one directory, and DBT-RISE
# relies on that. The fetched Boost has one target per library, so each
# library whose headers are used has to be named. DBT-RISE-RISCV passes on
# the core library's include path as it stood when it was configured, so it
# has to be told as well.
list(TRANSFORM _dbt_rise_boost PREPEND Boost::)
target_link_libraries(dbt-rise-core PUBLIC ${_dbt_rise_boost})
target_link_libraries(dbt-rise-riscv PUBLIC ${_dbt_rise_boost})
# LLVM's code calls the helpers by name, looked up in the running process,
# where asmjit's calls them by address. So nothing names them when a program
# is linked, and the linker leaves their file of the static library out: one
# of them is asked for by name, which brings in the rest. And on Linux an
# executable keeps its names to itself unless it is linked to export them.
if(WITH_LLVM)
  target_link_options(dbt-rise-core INTERFACE
    $<$<PLATFORM_ID:Linux>:-rdynamic LINKER:--undefined=iss_wait>
    $<$<PLATFORM_ID:Darwin>:LINKER:-u,_iss_wait>)
endif()
# The helpers the translating backends call. With none of them built the
# file is left out, as it always was, so that the interpreter's build is
# what it was before M26.
if(NOT SOCPUPPET_DBT_RISE_BACKENDS)
  get_target_property(_dbt_rise_core_sources dbt-rise-core SOURCES)
  list(REMOVE_ITEM _dbt_rise_core_sources src/iss/vm_jit_funcs.cpp)
  set_target_properties(dbt-rise-core PROPERTIES
    SOURCES "${_dbt_rise_core_sources}")
endif()
# The vector helpers specialize std::make_signed for 128-bit integers, which
# the standard forbids and newer Clangs treat as an error. PRIVATE, because
# an older Clang does not know the option, and it must not reach a target
# of ours, where an unknown option is an error itself.
target_compile_options(softvector PRIVATE
  $<$<CXX_COMPILER_ID:AppleClang,Clang>:-Wno-invalid-specialization>)
# Some of the interpreter's sources need over a gigabyte of memory each to
# compile, so only a few are compiled at once. (Ninja only; other
# generators ignore the pool.)
set_property(GLOBAL APPEND PROPERTY JOB_POOLS dbt_rise=${SOCPUPPET_DBT_RISE_JOBS})
set_target_properties(dbt-rise-riscv PROPERTIES JOB_POOL_COMPILE dbt_rise)

# --- SPDK's NVMe definitions (Intel and others, BSD-3-Clause) ----------------
# One header from the Storage Performance Development Kit: the registers,
# commands and data structures of the NVMe specification, as C structs whose
# sizes are checked against the specification at compile time. Only that
# file is fetched, into a directory called spdk so that it can be included
# as "spdk/nvme_spec.h".
#
# It includes two more SPDK headers, one of which pulls in most of POSIX.
# cmake/shims/spdk has small stand-ins for both (see docs/upstream.md).
FetchContent_Declare(spdk_nvme_spec
  # SPDK v26.09
  URL https://raw.githubusercontent.com/spdk/spdk/0bbb7fe4dccfb31e8d446da8822360704949d1e9/include/spdk/nvme_spec.h
  URL_HASH SHA256=cb5c830fdbc7e8ed702f9e22125b8d70ad7979ef5972cbbcbed04c2374678ffe
  DOWNLOAD_NO_EXTRACT TRUE
  SOURCE_DIR ${FETCHCONTENT_BASE_DIR}/spdk_nvme_spec-src/spdk)
FetchContent_MakeAvailable(spdk_nvme_spec)
add_library(spdk_nvme_spec INTERFACE)
target_include_directories(spdk_nvme_spec SYSTEM INTERFACE
  ${spdk_nvme_spec_SOURCE_DIR}/..
  ${CMAKE_CURRENT_LIST_DIR}/shims)

# --- VPV-Peripherals (VP-Vibes, Apache-2.0): borrowed peripheral models -----
# SystemC models of peripherals, built on SCC. Minres's own reference
# platform takes its peripherals from here.
#
# Only its sources are fetched. Its own CMake targets link all of SCC,
# including SCC's AXI and CHI protocol library, which needs a Boost library
# we do not fetch and does not compile here as C++20 (see docs/upstream.md).
# The models we borrow need SCC's register classes and nothing more, so
# each adapter names the files it uses.
FetchContent_Declare(vpv_peripherals
  GIT_REPOSITORY https://github.com/VP-Vibes/VPV-Peripherals.git
  GIT_TAG 8c70afcc74b7ac03ca822d8fbad0752ae6176a81 # 2026-09-23
  # aclint-time-zero: a timer compare value written at time zero was never
  # acted on.
  # aclint-write-ahead: a CPU that set the compare value while it was ahead
  # of the clock was charged the time it was ahead by a second time, so its
  # clock jumped at every write.
  # The four for the PLIC: its last source's priority was read
  # from past the end of an array; a source that was already pending when
  # it was enabled never interrupted; one whose line was still high when
  # its handler completed never interrupted again; and one whose line
  # pulsed while its handler was running was not heard.
  # uart-interrupt-from-state: the UART's interrupt was folded together
  # from a queue of events and came out wrong for a driver that enables an
  # interrupt whose cause is already there, as every driver does to start
  # transmitting.
  # aplic-msi-mode: the APLIC delivered over a line only. This adds
  # delivery by message, which a platform whose harts have IMSICs needs.
  # aon-watchdog: the model of SiFive's always-on block had the watchdog's
  # registers and nothing behind them. This adds the watchdog.
  PATCH_COMMAND git apply
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-aclint-time-zero.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-aclint-write-ahead.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-plic-last-source.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-plic-look-again.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-plic-level-sources.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-plic-edge-while-claimed.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-uart-interrupt-from-state.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-aplic-msi-mode.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-aon-watchdog.patch
  UPDATE_DISCONNECTED TRUE
  # A directory with no CMakeLists.txt, so that nothing of its build runs.
  SOURCE_SUBDIR .github)
FetchContent_MakeAvailable(vpv_peripherals)
