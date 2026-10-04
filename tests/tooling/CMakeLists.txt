# The tests of the repo's own tooling (tools/). They need the developer tools
# from `uv sync`, so they stay out of tests/python, which is also run against
# an installed wheel.
add_test(NAME tooling
  COMMAND ${Python_EXECUTABLE} -m pytest tests/tooling
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
