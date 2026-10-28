# Run the Python tests as part of ctest, against the extension just built.
# SOCPUPPET_TEST_PYTHON is the interpreter, under coverage.py when coverage
# is being measured (cmake/DevChecks.cmake).
#
# pytest-xdist runs them on every core. --dist loadscope keeps the tests of
# a class, or of a module of functions, on one worker, so that a fixture
# shared by the class is made once and not once on each worker. Without
# --no-loadscope-reorder it hands out the classes with the most tests
# first, and the boots of firmware, each a class of one long test, would
# start last (tests/python/conftest.py puts them first).
add_test(NAME pytest
  COMMAND ${SOCPUPPET_TEST_PYTHON} -m pytest
          -n auto --dist loadscope --no-loadscope-reorder
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# The examples are documentation that runs. Keep them running.
add_test(NAME example_passthrough_hello
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/passthrough_hello.py
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

add_test(NAME example_shell_from_python
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/shell_from_python.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_shell_from_python
                     PROPERTIES SKIP_RETURN_CODE 77)

add_test(NAME example_full_bootchain
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/full_bootchain.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_full_bootchain
                     PROPERTIES SKIP_RETURN_CODE 77)

add_test(NAME example_boot_from_flash
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${SOCPUPPET_TEST_PYTHON} examples/boot_from_flash.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
set_tests_properties(example_boot_from_flash
                     PROPERTIES SKIP_RETURN_CODE 77)

# These boot Linux: minutes on the interpreter, seconds on QBox's hart. So
# the two that stay at the console carry the label `qbox` and run on that
# hart alone: the dev and quick test presets leave them out, and the qbox
# test preset, which sets SOCPUPPET_CPU=qbox_cpu, runs them (tools/ci.py,
# the `qbox` job). The one with a cable carries `long`, as the pytest marker
# of that name means the same, and runs on the interpreter in the nightly
# run of the dev preset (the `test` job): under the pump, QBox's hart runs
# ahead of the clock and dropbear closes every ssh at the key exchange
# (docs/roadmap.md, the loose ends).
set(label_linux_hello qbox)
set(label_linux_on_the_drive qbox)
set(label_linux_cable long)
foreach(example linux_hello linux_on_the_drive linux_cable)
  add_test(NAME example_${example}
    COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
            ${SOCPUPPET_TEST_PYTHON} examples/${example}.py
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
  set_tests_properties(example_${example}
                       PROPERTIES SKIP_RETURN_CODE 77
                                  LABELS ${label_${example}})
endforeach()
