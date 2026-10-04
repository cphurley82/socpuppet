include(GoogleTest)

# Tests of plain C++ logic. No kernel, so they can share one process.
add_executable(unit_tests
  unit/memory_store_test.cpp)
target_link_libraries(unit_tests PRIVATE socpuppet_core GTest::gtest_main)
gtest_discover_tests(unit_tests)

# Tests that start the SystemC kernel. The kernel cannot be restarted, so
# gtest_discover_tests registers each test with CTest separately and CTest
# runs each one in its own process.
add_executable(kernel_tests
  kernel_test_main.cpp
  contracts/memory_test.cpp
  platform/kernel_smoke_test.cpp
  platform/scc_router_smoke_test.cpp
  platform/thin_slice_test.cpp)
target_link_libraries(kernel_tests PRIVATE socpuppet_models scc::components GTest::gtest)
gtest_discover_tests(kernel_tests)
