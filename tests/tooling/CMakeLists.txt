# Hold the whole tree to the lint rules, as CI does. `uv run python
# tools/lint.py --fix` repairs most of what this finds.
add_test(NAME lint
  COMMAND ${Python_EXECUTABLE} tools/lint.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# The tests of the repo's own tooling (tools/, cmake/). They need the
# developer tools from `uv sync`, so they stay out of tests/python, which is
# also run against an installed wheel.
add_test(NAME tooling
  COMMAND ${Python_EXECUTABLE} -m pytest tests/tooling
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# Neither runs any of the code that coverage measures, so the coverage
# target leaves both out (cmake/DevChecks.cmake).
set_tests_properties(lint tooling PROPERTIES LABELS ${SOCPUPPET_TOOLING_LABEL})
