# Run the Python tests as part of ctest, against the extension just built.
# SOCPUPPET_TEST_PYTHON is the interpreter, under coverage.py when coverage
# is being measured (cmake/DevChecks.cmake).
add_test(NAME pytest
  COMMAND ${SOCPUPPET_TEST_PYTHON} -m pytest
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# The examples are documentation that runs. Keep them running.
add_test(NAME example_m0_passthrough
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/m0_passthrough.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

add_test(NAME example_nvme_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/nvme_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# This one boots real firmware. Where the image has not been built it says
# so and is counted as skipped.
add_test(NAME example_host_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/host_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_host_hello PROPERTIES SKIP_RETURN_CODE 77)
