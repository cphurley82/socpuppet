# The ISS spike (milestone M1): exploratory code that compares CPU models
# behind a draft CPU slot. It is not part of socpuppet, nothing under src/,
# python/ or tests/ may depend on it, and it goes away when M3 builds the
# real CPU kit. See README.md here and docs/iss-spike.md.
include(GoogleTest)

# One test program per candidate, so that two candidates' symbols never
# meet in one link. Every test carries the label `spike`.
function(spike_test_program name)
  add_executable(${name}
    ${PROJECT_SOURCE_DIR}/tests/cpp/kernel_test_main.cpp
    ${ARGN})
  target_link_libraries(${name} PRIVATE
    socpuppet_models scc::components GTest::gmock)
  # Headers are included by their path from the top of the repository:
  # "spikes/iss/cpu_slot.h".
  target_include_directories(${name} PRIVATE ${PROJECT_SOURCE_DIR})
  socpuppet_dev_checks(${name})
  gtest_discover_tests(${name} PROPERTIES LABELS spike)
endfunction()

spike_test_program(spike_harness_tests harness/harness_test.cpp)
