# The NPU spike (milestone M12): exploratory code that compares AI
# processor candidates behind a draft accelerator slot. It is not part of
# socpuppet, nothing under src/, python/ or tests/ may depend on it, and
# what the decision keeps is rebuilt test-first in M19. See README.md here
# and docs/npu-spike.md.
#
# The Hexagon candidate is not built here: it needs QBox, which is built
# on its own in a container (hexagon/README.md).
include(GoogleTest)

# A test program of the spike's. Every test carries the label `spike`.
function(npu_spike_test_program name)
  add_executable(${name} ${ARGN})
  target_link_libraries(${name} PRIVATE
    socpuppet_builtin_components socpuppet_models scc::components GTest::gmock)
  # Headers are included by their path from the top of the repository:
  # "spikes/npu/doorbell.h", "tests/cpp/support/bus_driver.h".
  target_include_directories(${name} PRIVATE ${PROJECT_SOURCE_DIR})
  socpuppet_dev_checks(${name})
  gtest_discover_tests(${name} PROPERTIES LABELS spike)
endfunction()

# 🎭 The behavioral candidate, C++ flavour, and the doorbell on its own.
npu_spike_test_program(spike_npu_behavioral_tests
  ${PROJECT_SOURCE_DIR}/tests/cpp/kernel_test_main.cpp
  behavioral/behavioral_npu_test.cpp
  doorbell_test.cpp)

# 🧵 The numpy flavour embeds a Python interpreter, so it needs the
# library form of Python, which the extension does not. numpy comes from
# `uv sync --group spike`.
find_package(Python COMPONENTS Development.Embed)
if(Python_Development.Embed_FOUND)
  npu_spike_test_program(spike_npu_numpy_tests behavioral/numpy_npu_test.cpp)
  # Python::Python by name: pybind11 was configured before the Embed
  # component was asked for, so its embed target does not carry it.
  target_link_libraries(spike_npu_numpy_tests PRIVATE
    socpuppet_bindings pybind11::embed Python::Python)
  # Which Python the embedded interpreter is: the virtual environment's, so
  # that it finds numpy there.
  target_compile_definitions(spike_npu_numpy_tests PRIVATE
    SPIKE_PYTHON_EXECUTABLE="${Python_EXECUTABLE}")
else()
  message(STATUS "socpuppet: no Python library to embed, so the NPU spike's "
    "numpy flavour is not built")
endif()
