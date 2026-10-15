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
# The same loops on QBox's CPU, when socpuppet is built with QBox. The one
# file that includes QBox's headers is compiled on its own
# (socpuppet_qbox, in cmake/Dependencies.cmake). The tests register
# themselves, so the whole library is linked.
if(SOCPUPPET_HAS_QBOX)
  add_library(spike_speed_qbox STATIC qbox_speed_test.cpp)
  target_include_directories(spike_speed_qbox PRIVATE ${PROJECT_SOURCE_DIR})
  target_compile_definitions(spike_speed_qbox PRIVATE
    SPEED_COMPILER="${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
  target_link_libraries(spike_speed_qbox PRIVATE socpuppet_qbox GTest::gtest)
  target_link_libraries(spike_speed_tests PRIVATE
    $<LINK_LIBRARY:WHOLE_ARCHIVE,spike_speed_qbox>)
endif()
# Each test starts the SystemC kernel, so each runs in its own process,
# and they are timed, so never two at once (the `speed` test preset).
gtest_discover_tests(spike_speed_tests PROPERTIES LABELS speed)
