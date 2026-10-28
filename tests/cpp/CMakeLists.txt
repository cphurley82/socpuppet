include(GoogleTest)

# Tests of plain C++ logic. No kernel, so they can share one process.
add_executable(unit_tests
  unit/block_store_test.cpp
  unit/command_status_test.cpp
  unit/d2d_link_logic_test.cpp
  unit/dma_engine_logic_test.cpp
  unit/elf_image_test.cpp
  unit/flash_controller_logic_test.cpp
  unit/i2c_controller_logic_test.cpp
  unit/interrupt_file_test.cpp
  unit/iommu_walker_test.cpp
  unit/link_channel_test.cpp
  unit/little_endian_test.cpp
  unit/memory_store_test.cpp
  unit/nand_array_test.cpp
  unit/nvme_controller_test.cpp
  unit/nvme_frontend_logic_test.cpp
  unit/nvme_host_registers_test.cpp
  unit/pcie_endpoint_registers_test.cpp
  unit/pciem_host_logic_test.cpp
  unit/prp_test.cpp
  unit/qbox_fates_test.cpp
  unit/rtc_logic_test.cpp
  unit/script_test.cpp
  unit/spi_nor_chip_test.cpp
  unit/system_controller_logic_test.cpp
  unit/ucie_link_registers_test.cpp
  unit/ucie_link_state_test.cpp
  unit/ucie_sideband_test.cpp
  unit/virtio_9p_logic_test.cpp
  unit/virtio_console_logic_test.cpp
  unit/virtio_fs_logic_test.cpp
  unit/virtio_blk_logic_test.cpp
  unit/virtio_mmio_logic_test.cpp
  unit/virtio_net_logic_test.cpp
  unit/virtio_rng_logic_test.cpp
  unit/virtqueue_test.cpp)
# The tests write their own ELF images, with the library that reads them.
target_link_libraries(unit_tests PRIVATE
  socpuppet_core socpuppet_vpvper elfio::elfio GTest::gmock_main)
# As for the kernel tests below: "tests/cpp/support/elf_file.h".
target_include_directories(unit_tests PRIVATE ${PROJECT_SOURCE_DIR})
socpuppet_dev_checks(unit_tests)
# What every C++ test is registered with. The label lets a test run pick
# out the C++ tests (the asan preset does). The slowest C++ test takes a
# few seconds, so one that runs for two minutes has hung: it fails then,
# where with no timeout a hang holds a CI job until the runner gives up on
# it, hours later, with nothing uploaded.
set(SOCPUPPET_CPP_TEST_PROPERTIES LABELS cpp TIMEOUT 120)
gtest_discover_tests(unit_tests PROPERTIES ${SOCPUPPET_CPP_TEST_PROPERTIES})

# Tests that start the SystemC kernel. The kernel cannot be restarted, so
# gtest_discover_tests registers each test with CTest separately and CTest
# runs each one in its own process.
add_executable(kernel_tests
  kernel_test_main.cpp
  contracts/aplic_test.cpp
  contracts/bus_master_test.cpp
  contracts/gpio_test.cpp
  contracts/interrupt_controller_test.cpp
  contracts/iommu_test.cpp
  contracts/link_test.cpp
  contracts/machine_timer_test.cpp
  contracts/memory_test.cpp
  contracts/message_controller_test.cpp
  contracts/nand_test.cpp
  contracts/nvme_test.cpp
  contracts/rom_test.cpp
  contracts/spi_controller_test.cpp
  contracts/uart_test.cpp
  contracts/virtio_device_test.cpp
  contracts/watchdog_test.cpp
  platform/aplic_test.cpp
  platform/composition_test.cpp
  platform/cpu_test.cpp
  platform/d2d_link_test.cpp
  platform/dma_engine_test.cpp
  platform/flash_controller_test.cpp
  platform/i2c_controller_test.cpp
  platform/msi_receiver_test.cpp
  platform/ns16550_test.cpp
  platform/nvme_frontend_test.cpp
  platform/pcie_test.cpp
  platform/pciem_host_test.cpp
  platform/qbox_cpu_test.cpp
  platform/router_test.cpp
  platform/scripted_master_test.cpp
  platform/spi_flash_test.cpp
  platform/system_controller_test.cpp
  platform/tracer_test.cpp
  platform/virtio_console_test.cpp
  platform/virtio_net_test.cpp
  platform/transport_test.cpp)
target_link_libraries(kernel_tests PRIVATE
  socpuppet_builtin_components socpuppet_models scc::components GTest::gmock)
# The tests' own headers are included by their path from the top of the
# repository: "tests/cpp/support/bus_driver.h".
target_include_directories(kernel_tests PRIVATE ${PROJECT_SOURCE_DIR})
socpuppet_dev_checks(kernel_tests)
# What the CPU tests expect a CPU to run with when nothing says.
target_compile_definitions(kernel_tests PRIVATE
  SOCPUPPET_DBT_RISE_DEFAULT_BACKEND="${SOCPUPPET_DBT_RISE_DEFAULT_BACKEND}")
gtest_discover_tests(kernel_tests
  PROPERTIES ${SOCPUPPET_CPP_TEST_PROPERTIES})

# The ring pciem posts the host's writes on, in a build with pciem only.
# Its test includes pciem's header, which needs C++23, and SystemC refuses
# to link with that, so it is a program of its own with no kernel.
if(SOCPUPPET_HAS_PCIEM)
  add_executable(pciem_ring_tests unit/pciem_ring_test.cpp)
  target_link_libraries(pciem_ring_tests PRIVATE
    socpuppet_pciem_device GTest::gmock_main)
  target_include_directories(pciem_ring_tests SYSTEM PRIVATE
    ${SOCPUPPET_PCIEM_DIR})
  set_target_properties(pciem_ring_tests PROPERTIES CXX_STANDARD 23)
  socpuppet_dev_checks(pciem_ring_tests)
  gtest_discover_tests(pciem_ring_tests
    PROPERTIES ${SOCPUPPET_CPP_TEST_PROPERTIES})
endif()
