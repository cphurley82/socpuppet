include(GoogleTest)

# Tests of plain C++ logic. No kernel, so they can share one process.
add_executable(unit_tests
  unit/elf_image_test.cpp
  unit/memory_store_test.cpp
  unit/nvme_controller_test.cpp
  unit/prp_test.cpp
  unit/script_test.cpp)
# The tests write their own ELF images, with the library that reads them.
target_link_libraries(unit_tests PRIVATE
  socpuppet_core elfio::elfio GTest::gmock_main)
# As for the kernel tests below: "tests/cpp/support/elf_file.h".
target_include_directories(unit_tests PRIVATE ${PROJECT_SOURCE_DIR})
socpuppet_dev_checks(unit_tests)
# The label lets a test run pick out the C++ tests (the asan preset does).
gtest_discover_tests(unit_tests PROPERTIES LABELS cpp)

# Tests that start the SystemC kernel. The kernel cannot be restarted, so
# gtest_discover_tests registers each test with CTest separately and CTest
# runs each one in its own process.
add_executable(kernel_tests
  kernel_test_main.cpp
  contracts/bus_master_test.cpp
  contracts/interrupt_controller_test.cpp
  contracts/link_test.cpp
  contracts/machine_timer_test.cpp
  contracts/memory_test.cpp
  contracts/nvme_test.cpp
  contracts/uart_test.cpp
  platform/composition_test.cpp
  platform/cpu_test.cpp
  platform/kernel_smoke_test.cpp
  platform/msi_receiver_test.cpp
  platform/router_test.cpp
  platform/scc_router_smoke_test.cpp
  platform/scripted_master_test.cpp
  platform/tracer_test.cpp)
target_link_libraries(kernel_tests PRIVATE socpuppet_models scc::components GTest::gmock)
# The tests' own headers are included by their path from the top of the
# repository: "tests/cpp/contracts/bus_driver.h".
target_include_directories(kernel_tests PRIVATE ${PROJECT_SOURCE_DIR})
socpuppet_dev_checks(kernel_tests)
gtest_discover_tests(kernel_tests PROPERTIES LABELS cpp)
