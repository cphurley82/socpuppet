# The boot spike (milestone M14, step 0): exploratory code that asks four
# questions of the pieces M14 borrows before any of its steps is written.
# It is not part of socpuppet, and nothing under src/, python/ or tests/
# may depend on it. See README.md here and docs/boot-spike.md.
include(GoogleTest)

# VPV-Peripherals' SPI controller and the flash chip that goes with it,
# built apart from ours so that our warnings leave them alone.
add_library(spike_vpv_flash STATIC
  ${vpv_peripherals_SOURCE_DIR}/minres/qspi.cpp
  ${vpv_peripherals_SOURCE_DIR}/generic/spi_mem.cpp)
target_compile_definitions(spike_vpv_flash PUBLIC SC_SIGNAL_IF)
target_compile_options(spike_vpv_flash PRIVATE -w)
# SCC's SPI sockets are headers, in the directory of its `interfaces`
# library. That library is not linked: it has AXI and CHI in it as well,
# which this build has never compiled and whose transaction recording
# does not compile with this clang.
target_include_directories(spike_vpv_flash SYSTEM PUBLIC
  ${vpv_peripherals_SOURCE_DIR} ${scc_SOURCE_DIR}/src/interfaces)
target_link_libraries(spike_vpv_flash
  PUBLIC scc::components SystemC::systemc
  PRIVATE elfio::elfio)

add_executable(spike_boot_flash_rig
  ${PROJECT_SOURCE_DIR}/tests/cpp/kernel_test_main.cpp
  flash_rig_test.cpp)
target_link_libraries(spike_boot_flash_rig PRIVATE
  spike_vpv_flash socpuppet_platform GTest::gmock)
target_include_directories(spike_boot_flash_rig PRIVATE
  ${PROJECT_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/src)
gtest_discover_tests(spike_boot_flash_rig PROPERTIES LABELS spike)
