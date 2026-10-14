# The speed spike's loops on QBox (milestone M26). A project of its own,
# because QBox is built separately (build.sh) and its SystemC cannot be
# linked with socpuppet's. It shares loops.h and the CPU tests' assembler,
# which are headers.
#
#   cmake -S spikes/speed/qbox -B $QBOX_ROOT/speed -DQBOX_ROOT=$QBOX_ROOT/src/build/install
#   cmake --build $QBOX_ROOT/speed
cmake_minimum_required(VERSION 3.24)
project(spike_speed_qbox CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

set(SOCPUPPET_ROOT ${CMAKE_CURRENT_LIST_DIR}/../../..)
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

add_executable(spike_speed_qbox_tests qbox_speed_test.cpp)
target_include_directories(spike_speed_qbox_tests PRIVATE ${SOCPUPPET_ROOT})
# The CPU is a plug-in: its header is installed beside the package.
target_include_directories(spike_speed_qbox_tests SYSTEM PRIVATE
  ${QBOX_ROOT}/qemu-components/cpu_riscv/cpu_riscv64/include)
target_compile_definitions(spike_speed_qbox_tests PRIVATE
  SPEED_COMPILER="${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
target_link_libraries(spike_speed_qbox_tests PRIVATE qbox::qbox GTest::gtest)
