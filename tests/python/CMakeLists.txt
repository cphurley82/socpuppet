# Run the Python tests as part of ctest, against the extension just built.
add_test(NAME pytest
  COMMAND ${Python_EXECUTABLE} -m pytest
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# The examples are documentation that runs. Keep them running.
add_test(NAME example_m0_passthrough
  COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${PROJECT_SOURCE_DIR}/python
          ${Python_EXECUTABLE} examples/m0_passthrough.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
