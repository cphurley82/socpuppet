# QBox behind the spike's CPU slot. A project of its own, because QBox
# cannot be a part of socpuppet's build: it is built separately (see
# ../build.sh, with QBOX_CXX_STANDARD=20), installed, and found here as a
# package. socpuppet's side is its header-only platform layer.
#
# Configured and built inside the QBox container:
#   cmake -S /workspace/spikes/iss/qbox/integration -B /qbox/integration
#   cmake --build /qbox/integration && ctest --test-dir /qbox/integration
cmake_minimum_required(VERSION 3.24)
project(spike_qbox_integration CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

set(SOCPUPPET_ROOT ${CMAKE_CURRENT_LIST_DIR}/../../../..)
set(QBOX_ROOT /qbox/src/build/install CACHE PATH "Where QBox is installed")
list(APPEND CMAKE_PREFIX_PATH ${QBOX_ROOT})
find_package(qbox REQUIRED)

include(FetchContent)
set(INSTALL_GTEST OFF)
FetchContent_Declare(googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.18.0.tar.gz
  URL_HASH SHA256=6e3191c1455468b3fc35a417fb565c1c5071aee1b7e7f85e30cf48a98d37d8b5
  EXCLUDE_FROM_ALL SYSTEM)
FetchContent_MakeAvailable(googletest)
include(GoogleTest)
enable_testing()

add_executable(spike_qbox_tests qbox_test.cpp)
target_include_directories(spike_qbox_tests PRIVATE
  ${SOCPUPPET_ROOT} ${SOCPUPPET_ROOT}/src)
# The CPU components are plug-ins: their headers are installed, but not as
# part of the package.
target_include_directories(spike_qbox_tests SYSTEM PRIVATE
  ${QBOX_ROOT}/qemu-components/cpu_riscv/cpu_riscv64/include
  ${QBOX_ROOT}/qemu-components/cpu_riscv/cpu_riscv32/include)
target_compile_definitions(spike_qbox_tests PRIVATE
  SPIKE_WITHOUT_SCC
  SPIKE_FIRMWARE_DIR="${SOCPUPPET_ROOT}/build/firmware")
target_compile_options(spike_qbox_tests PRIVATE -Wall -Wextra)
target_link_libraries(spike_qbox_tests PRIVATE qbox::qbox GTest::gmock)
gtest_discover_tests(spike_qbox_tests PROPERTIES LABELS spike)
