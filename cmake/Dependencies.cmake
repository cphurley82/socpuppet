# Third-party dependencies, pinned. Everything is built from source as a
# static library so one binary holds exactly one SystemC kernel.
include(FetchContent)

# EXCLUDE_FROM_ALL keeps a dependency's install rules out of our wheel.
# SYSTEM silences warnings from its headers.

FetchContent_Declare(systemc
  URL https://github.com/accellera-official/systemc/archive/refs/tags/3.0.2.tar.gz
  URL_HASH SHA256=9b3693ed286aab958b9e5d79bb0ad3bc523bbc46931100553275352038f4a0c4
  EXCLUDE_FROM_ALL SYSTEM)

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

FetchContent_MakeAvailable(systemc pybind11)

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

# SCC probes for SystemC by compiling against an installed copy. Ours is
# built in this same tree, so tell SCC it is already found.
set(SystemC_FOUND TRUE)
set(SystemC_LIBRARIES SystemC::systemc)
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
set(WITH_TCC OFF)
set(WITH_ASMJIT OFF)
set(WITH_LLVM OFF)
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
  PATCH_COMMAND git apply
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-offsetof.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-reset-restart.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-static-library.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-dmi-invalidate.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-riscv-interrupt-after-access.patch
  UPDATE_DISCONNECTED TRUE
  EXCLUDE_FROM_ALL SYSTEM)
# DBT-RISE-RISCV fetches its core library itself, under this name and at
# this commit. Declaring it here first is how the patches get applied.
FetchContent_Declare(dbt_rise_core_git
  GIT_REPOSITORY https://github.com/Minres/DBT-RISE-Core.git
  GIT_TAG 29e97c021c988370f5c5af5b5076afe8043402b6
  # asio-names: Boost 1.87 removed the names its GDB server used.
  # int128-traits: it specialized a private template of GCC's standard
  # library, which Clang's library does not have.
  PATCH_COMMAND git apply
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-asio-names.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/dbt-rise-core-int128-traits.patch
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
# A helper for the translating backends declares a C function called wait(),
# which POSIX has already taken, and on macOS the two collide. No such
# backend is built, so the file is left out.
get_target_property(_dbt_rise_core_sources dbt-rise-core SOURCES)
list(REMOVE_ITEM _dbt_rise_core_sources src/iss/vm_jit_funcs.cpp)
set_target_properties(dbt-rise-core PROPERTIES
  SOURCES "${_dbt_rise_core_sources}")
# The vector helpers specialize std::make_signed for 128-bit integers, which
# the standard forbids and newer Clangs treat as an error. PRIVATE, because
# an older Clang does not know the option, and it must not reach a target
# of ours, where an unknown option is an error itself.
target_compile_options(softvector PRIVATE
  $<$<CXX_COMPILER_ID:AppleClang,Clang>:-Wno-invalid-specialization>)
# Some of the interpreter's sources need over a gigabyte of memory each to
# compile, so only a few are compiled at once. (Ninja only; other
# generators ignore the pool.)
set_property(GLOBAL APPEND PROPERTY JOB_POOLS dbt_rise=4)
set_target_properties(dbt-rise-riscv PROPERTIES JOB_POOL_COMPILE dbt_rise)

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
  # acted on. The three for the PLIC: its last source's priority was read
  # from past the end of an array; a source that was already pending when
  # it was enabled never interrupted; and one whose line was still high
  # when its handler completed never interrupted again.
  PATCH_COMMAND git apply
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-aclint-time-zero.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-plic-last-source.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-plic-look-again.patch
    ${CMAKE_CURRENT_LIST_DIR}/patches/vpv-peripherals-plic-level-sources.patch
  UPDATE_DISCONNECTED TRUE
  # A directory with no CMakeLists.txt, so that nothing of its build runs.
  SOURCE_SUBDIR .github)
FetchContent_MakeAvailable(vpv_peripherals)
