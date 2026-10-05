include(GoogleTest)

# Tests of plain C++ logic. No kernel, so they can share one process.
add_executable(unit_tests
  unit/memory_store_test.cpp
  unit/script_test.cpp)
target_link_libraries(unit_tests PRIVATE socpuppet_core GTest::gtest_main)
socpuppet_dev_checks(unit_tests)
# The label lets a test run pick out the C++ tests (the asan preset does).
gtest_discover_tests(unit_tests PROPERTIES LABELS cpp)

# Tests that start the SystemC kernel. The kernel cannot be restarted, so
# gtest_discover_tests registers each test with CTest separately and CTest
# runs each one in its own process.
add_executable(kernel_tests
  kernel_test_main.cpp
  contracts/link_test.cpp
  contracts/memory_test.cpp
  contracts/uart_test.cpp
  platform/composition_test.cpp
  platform/cpu_test.cpp
  platform/kernel_smoke_test.cpp
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
