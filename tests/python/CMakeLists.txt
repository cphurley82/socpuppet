# Run the Python tests as part of ctest, against the extension just built.
# SOCPUPPET_TEST_PYTHON is the interpreter, under coverage.py when coverage
# is being measured (cmake/DevChecks.cmake).
#
# They are three entries, so that a test preset chooses among them by label
# (CMakePresets.json): `pytest`, the tests that take well under a second,
# which every preset runs; `pytest_boots`, one boot of real firmware for each
# area (tests/python/conftest.py, the `representative` marker), which every
# push runs; and `pytest_long`, every other boot, labelled `nightly`, when it
# runs.
#
# pytest-xdist runs them on every core. --dist loadgroup hands them out a
# test at a time, but for the groups socpuppet's plugin makes of a class
# whose tests share one process and one boot, platform(scope="class"),
# which go to one worker together. Without --no-loadscope-reorder it hands
# out the biggest groups first, and the other boots would start last
# (tests/python/conftest.py puts them first).
function(socpuppet_add_pytest name marks label)
  add_test(NAME ${name}
    COMMAND ${SOCPUPPET_TEST_PYTHON} -m pytest -m ${marks}
            -n auto --dist loadgroup --no-loadscope-reorder
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
  set_tests_properties(${name} PROPERTIES LABELS ${label})
endfunction()
socpuppet_add_pytest(pytest "not long" python)
socpuppet_add_pytest(pytest_boots representative boots)
socpuppet_add_pytest(pytest_long "long and not representative" nightly)

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

# Each is a few seconds, and runs in the quick test preset.
set_tests_properties(
  example_passthrough_hello example_nvme_hello example_ssd_hello
  example_io_manager_hello example_host_hello example_ssd_firmware_hello
  example_host_and_ssd_hello example_chiplet_host_hello
  example_shell_from_python example_full_bootchain example_boot_from_flash
  PROPERTIES LABELS example)

# These boot Linux: minutes on the interpreter, seconds on QBox's hart. So
# the two that stay at the console carry the label `qbox` and run on that
# hart alone: the dev and quick test presets leave them out, and the qbox
# test preset, which sets SOCPUPPET_CPU=qbox_cpu, runs them (tools/ci.py,
# the `qbox` job). The one with a cable carries `nightly`, as the long tests
# the quick test preset leaves out do, and runs on the interpreter in the
# nightly run of the dev preset (the `test` job). It carries `interpreter`
# too, which the qbox test preset leaves out: under the pump, QBox's hart
# runs ahead of the clock and dropbear closes every ssh at the key exchange
# (docs/roadmap.md, the loose ends).
set(label_linux_hello qbox)
set(label_linux_on_the_drive qbox)
set(label_linux_cable "nightly;interpreter")
foreach(example linux_hello linux_on_the_drive linux_cable)
  add_test(NAME example_${example}
    COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
            ${SOCPUPPET_TEST_PYTHON} examples/${example}.py
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
  set_tests_properties(example_${example}
                       PROPERTIES SKIP_RETURN_CODE 77
                                  LABELS "${label_${example}}")
endforeach()
