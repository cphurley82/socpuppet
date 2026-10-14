# The speed spike (milestone M26): the host's core timed on three loops,
# on every CPU and every machine it can be built on. It is not part of
# socpuppet and nothing under src/, python/ or tests/ may depend on it,
# but unlike M1's harness it stays: a change to the core can be timed
# against what is in results/. See README.md here and docs/speed-spike.md.
include(GoogleTest)

add_executable(spike_speed_tests
  ${PROJECT_SOURCE_DIR}/tests/cpp/kernel_test_main.cpp
  speed_test.cpp)
target_link_libraries(spike_speed_tests PRIVATE
  socpuppet_builtin_components socpuppet_models scc::components GTest::gtest)
# Headers are included by their path from the top of the repository.
target_include_directories(spike_speed_tests PRIVATE ${PROJECT_SOURCE_DIR})
# What the lines say the program was compiled with.
target_compile_definitions(spike_speed_tests PRIVATE
  SPEED_COMPILER="${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
socpuppet_dev_checks(spike_speed_tests)
# Each test starts the SystemC kernel, so each runs in its own process,
# and they are timed, so never two at once (the `speed` test preset).
gtest_discover_tests(spike_speed_tests PROPERTIES LABELS speed)
