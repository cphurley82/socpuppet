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

add_test(NAME example_ssd_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/ssd_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

add_test(NAME example_io_manager_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/io_manager_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# This one boots real firmware. Where the image has not been built it says
# so and is counted as skipped.
add_test(NAME example_host_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/host_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_host_hello PROPERTIES SKIP_RETURN_CODE 77)

add_test(NAME example_ssd_firmware_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/ssd_firmware_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_ssd_firmware_hello
                     PROPERTIES SKIP_RETURN_CODE 77)

add_test(NAME example_host_and_ssd_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/host_and_ssd_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_host_and_ssd_hello
                     PROPERTIES SKIP_RETURN_CODE 77)

add_test(NAME example_chiplet_host_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/chiplet_host_hello.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_chiplet_host_hello
                     PROPERTIES SKIP_RETURN_CODE 77)

add_test(NAME example_full_bootchain
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/full_bootchain.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_full_bootchain
                     PROPERTIES SKIP_RETURN_CODE 77)
