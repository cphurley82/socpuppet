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

include(cmake/Dependencies.cmake)

add_subdirectory(src/socpuppet)

enable_testing()
add_subdirectory(tests/cpp)
add_subdirectory(tests/python)
