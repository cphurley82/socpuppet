cmake_minimum_required(VERSION 3.28)
project(socpuppet LANGUAGES CXX C)

# SystemC bakes the C++ standard into a link-time check, so the library and
# everything that links it must agree. Set it once, before any dependency.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
option(BUILD_SHARED_LIBS "Build dependencies as shared libraries" OFF)
option(SOCPUPPET_BUILD_TESTS "Build the C++ tests and register pytest with ctest" ON)

include(cmake/Dependencies.cmake)

add_subdirectory(src/socpuppet)

if(SOCPUPPET_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests/cpp)
  add_subdirectory(tests/python)
  add_subdirectory(tests/tooling)
endif()
