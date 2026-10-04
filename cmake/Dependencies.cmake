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

set(BOOST_INCLUDE_LIBRARIES date_time filesystem)
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
  # this same tree. The patch points the probe at SystemC's headers instead.
  PATCH_COMMAND git apply ${CMAKE_CURRENT_LIST_DIR}/patches/scc-in-tree-systemc.patch
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
