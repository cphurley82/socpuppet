# Run the Python tests as part of ctest, against the extension just built.
add_test(NAME pytest
  COMMAND ${Python_EXECUTABLE} -m pytest
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
