include(GoogleTest)

# Tests that start the SystemC kernel. The kernel cannot be restarted, so
# gtest_discover_tests registers each test with CTest separately and CTest
# runs each one in its own process.
add_executable(kernel_tests
  kernel_test_main.cpp
  platform/kernel_smoke_test.cpp
  platform/scc_router_smoke_test.cpp)
target_link_libraries(kernel_tests PRIVATE scc::components SystemC::systemc GTest::gtest)
gtest_discover_tests(kernel_tests)
