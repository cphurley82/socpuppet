# QBox's Hexagon behind the spike's accelerator slot. A project of its
# own, because QBox cannot be a part of socpuppet's build: it is built
# separately (see ../build.sh), installed, and found here as a package.
# socpuppet's side is header-only.
#
# Configured and built inside the container:
#   cmake -S /workspace/spikes/npu/hexagon/integration -B /qbox/integration
#   cmake --build /qbox/integration && ctest --test-dir /qbox/integration
cmake_minimum_required(VERSION 3.24)
project(spike_hexagon_integration C CXX)

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

# ---- The program the core runs --------------------------------------------
# Ubuntu's clang has the Hexagon back end in it. Bare metal: no C library,
# no builtins, and no HVX (the vector unit), which this program does not
# use and QEMU would have to be told about.
set(_firmware ${CMAKE_CURRENT_LIST_DIR}/../firmware)
set(_hexagon_flags --target=hexagon-unknown-elf -mv68 -mno-hvx -O2
  -ffreestanding -fno-builtin -nostdlib -fno-pic)
add_custom_command(
  OUTPUT matmul.bin
  COMMAND clang ${_hexagon_flags} -c ${_firmware}/matmul.c -o matmul.o
  COMMAND clang ${_hexagon_flags} -c ${_firmware}/start.S -o start.o
  COMMAND ld.lld -T ${_firmware}/firmware.ld -o matmul.elf start.o matmul.o
  COMMAND llvm-objcopy -O binary matmul.elf matmul.bin
  DEPENDS ${_firmware}/matmul.c ${_firmware}/start.S ${_firmware}/firmware.ld
  COMMENT "Compiling the Hexagon program")
add_custom_target(hexagon_program DEPENDS matmul.bin)

# ---- The test ----------------------------------------------------------------
add_executable(spike_hexagon_tests hexagon_npu_test.cpp)
add_dependencies(spike_hexagon_tests hexagon_program)
target_include_directories(spike_hexagon_tests PRIVATE
  ${SOCPUPPET_ROOT} ${SOCPUPPET_ROOT}/src
  # The generated register headers (the doorbell's status bits are a
  # command device's).
  ${SOCPUPPET_ROOT}/python/socpuppet/zephyr_module/include)
# The Hexagon components are plug-ins: their headers are installed next to
# the package, not as part of it.
file(GLOB _qbox_component_includes
  ${QBOX_ROOT}/qemu-components/*/include
  ${QBOX_ROOT}/qemu-components/*/*/include)
target_include_directories(spike_hexagon_tests SYSTEM PRIVATE
  ${_qbox_component_includes})
target_compile_definitions(spike_hexagon_tests PRIVATE
  SPIKE_HEXAGON_PROGRAM="${CMAKE_CURRENT_BINARY_DIR}/matmul.bin")
target_compile_options(spike_hexagon_tests PRIVATE -Wall -Wextra)
# The Hexagon core, its global registers, its TLB and its interrupt
# controller are plug-ins: shared libraries in QBox's install with no `lib`
# prefix, so they are named by path.
set(_qbox_hexagon_libraries)
foreach(_plugin qemu_cpu_hexagon hexagon_globalreg hexagon_tlb hexagon_l2vic)
  list(APPEND _qbox_hexagon_libraries ${QBOX_ROOT}/lib/${_plugin}.so)
endforeach()
target_link_libraries(spike_hexagon_tests PRIVATE
  qbox::qbox ${_qbox_hexagon_libraries} GTest::gmock)
gtest_discover_tests(spike_hexagon_tests PROPERTIES LABELS spike)
