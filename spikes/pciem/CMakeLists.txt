# The real-host spike (milestone M30): this machine's own Linux mounts the
# puppet's SSD, through pciem. Exploratory code, not part of socpuppet;
# nothing under src/, python/ or tests/ may depend on it. See README.md here
# and docs/history/real-host-spike.md.
#
# pciem is GPL-2.0-only and is not in the build: spikes/pciem/fetch.sh puts
# it in build/pciem, and PCIEM_DIR says where it is.
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  return()
endif()
set(PCIEM_DIR "${PROJECT_SOURCE_DIR}/build/pciem" CACHE PATH
  "Where spikes/pciem/fetch.sh put pciem")
if(NOT EXISTS "${PCIEM_DIR}/include/pciem_api.h")
  message(STATUS "socpuppet: no pciem in ${PCIEM_DIR}, so the real-host "
    "spike is not built (spikes/pciem/fetch.sh fetches it)")
  return()
endif()
include(GoogleTest)

# The calls to /dev/pciem, in the one source file that includes pciem's
# header, which needs C++23 for its <stdatomic.h>.
add_library(spike_pciem_device STATIC pciem_device.cpp)
target_include_directories(spike_pciem_device
  PUBLIC ${PROJECT_SOURCE_DIR} PRIVATE ${PCIEM_DIR})
set_target_properties(spike_pciem_device PROPERTIES CXX_STANDARD 23)
socpuppet_dev_checks(spike_pciem_device)

# The program that puts a drive on this machine's bus.
add_executable(spike_pciem_host host_spike.cpp)
target_link_libraries(spike_pciem_host PRIVATE spike_pciem_device
  socpuppet_builtin_components socpuppet_models scc::components GTest::gmock)
socpuppet_dev_checks(spike_pciem_host)

# What can be tried without /dev/pciem. Every test carries the label `spike`.
# SystemC is built for C++20 and refuses to link with C++23, so the ring's
# test, which includes pciem's header, is a program of its own.
add_executable(spike_pciem_ring_tests ring_test.cpp)
target_link_libraries(spike_pciem_ring_tests PRIVATE spike_pciem_device
  GTest::gtest_main)
target_include_directories(spike_pciem_ring_tests PRIVATE ${PCIEM_DIR})
set_target_properties(spike_pciem_ring_tests PROPERTIES CXX_STANDARD 23)
socpuppet_dev_checks(spike_pciem_ring_tests)
gtest_discover_tests(spike_pciem_ring_tests PROPERTIES LABELS spike)

add_executable(spike_pciem_bridge_tests
  ${PROJECT_SOURCE_DIR}/tests/cpp/kernel_test_main.cpp
  pciem_bridge_test.cpp)
target_link_libraries(spike_pciem_bridge_tests PRIVATE spike_pciem_device
  socpuppet_builtin_components socpuppet_models scc::components GTest::gmock)
socpuppet_dev_checks(spike_pciem_bridge_tests)
gtest_discover_tests(spike_pciem_bridge_tests PROPERTIES LABELS spike)
