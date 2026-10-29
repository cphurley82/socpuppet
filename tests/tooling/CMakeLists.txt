# Hold the whole tree to the lint rules, as CI does. `uv run python
# tools/lint.py --fix` repairs most of what this finds.
add_test(NAME lint
  COMMAND ${Python_EXECUTABLE} tools/lint.py
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# The tests of the repo's own tooling (tools/, cmake/). They need the
# developer tools from `uv sync`, so they stay out of tests/python, which is
# also run against an installed wheel. They run on every core, handed out
# a test at a time: a module of them shares no fixture worth keeping on one
# worker, and test_ci.py's, each a run of tools/ci.py of seconds, would
# take minutes one after another.
add_test(NAME tooling
  COMMAND ${Python_EXECUTABLE} -m pytest -n auto --dist load tests/tooling
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

# Neither runs any of the code that coverage measures, so the coverage
# target leaves both out (cmake/DevChecks.cmake).
set_tests_properties(lint tooling PROPERTIES LABELS ${SOCPUPPET_TOOLING_LABEL})
