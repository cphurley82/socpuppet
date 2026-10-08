cmake_minimum_required(VERSION 3.28)
project(socpuppet LANGUAGES CXX C)

# SystemC bakes the C++ standard into a link-time check, so the library and
# everything that links it must agree. Set it once, before any dependency.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
# Nothing here or in the dependencies is a C++20 module, so the compiler is
# not asked to look for any. With GCC 14, CMake would scan every source
# first, which costs a step per file and passes options that the ccache in
# the wheel builds' image is too old to know.
set(CMAKE_CXX_SCAN_FOR_MODULES OFF)
option(BUILD_SHARED_LIBS "Build dependencies as shared libraries" OFF)
option(SOCPUPPET_BUILD_TESTS "Build the C++ tests and register pytest with ctest" ON)

include(cmake/Dependencies.cmake)
include(cmake/DevChecks.cmake)

# The presets share one build directory, so the tree holds whichever kind of
# build was configured last. Say so when it is not the everyday one.
if(SOCPUPPET_COVERAGE)
  message(NOTICE "socpuppet: this build tree measures COVERAGE: our code is "
    "built unoptimized and instrumented. Run `cmake --preset dev` to go back.")
endif()
if(SOCPUPPET_SANITIZE)
  message(NOTICE "socpuppet: this build tree has SANITIZERS in the C++ tests. "
    "Run `cmake --preset dev` to go back.")
endif()

add_subdirectory(src/socpuppet)

if(SOCPUPPET_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests/cpp)
  add_subdirectory(tests/python)
  add_subdirectory(tests/tooling)
endif()
