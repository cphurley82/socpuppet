"""cmake/DevChecks.cmake: the `coverage` target.

It runs the tests and reports which lines of our own code they ran.
"""

WIDGET_HEADER = """\
#ifndef WIDGETS_WIDGET_H_
#define WIDGETS_WIDGET_H_

inline int AtMostTen(int number) {
  if (number > 10) {
    return 10;
  }
  return number;
}

#endif  // WIDGETS_WIDGET_H_
"""

VENDOR_HEADER = """\
inline int Answer() { return 42; }
"""

# Runs every line of AtMostTen() except `return 10;`.
WIDGET_TEST = """\
#include <vendor.h>

#include "widgets/widget.h"

int main() { return AtMostTen(Answer() - 42); }
"""

CMAKE_LISTS = """\
enable_testing()
add_executable(widget_test tests/widget_test.cpp)
target_include_directories(widget_test PRIVATE src)
target_include_directories(widget_test SYSTEM PRIVATE vendor)
add_test(NAME widget_test COMMAND widget_test)
socpuppet_dev_checks(widget_test)
"""


def widget_project(cmake_project, *options):
    """A configured project: a header of ours, a vendor's, and a test."""
    project = cmake_project(
        {
            "src/widgets/widget.h": WIDGET_HEADER,
            "vendor/vendor.h": VENDOR_HEADER,
            "tests/widget_test.cpp": WIDGET_TEST,
        },
        CMAKE_LISTS,
    )
    configured = project.configure("SOCPUPPET_COVERAGE=ON", *options)
    assert configured.returncode == 0, configured.stdout
    return project


def test_the_coverage_report_lists_our_header_but_not_a_vendors_or_the_test(
    cmake_project,
):
    project = widget_project(cmake_project)

    result = project.build("coverage")

    assert reported_files(result.stdout) == ["src/widgets/widget.h"]


def test_when_fewer_lines_are_run_than_the_floor_asks_for_coverage_fails(
    cmake_project,
):
    # One line of the header never runs, so it is short of 100%.
    project = widget_project(cmake_project, "SOCPUPPET_COVERAGE_CPP_FLOOR=100")

    result = project.build("coverage")

    assert result.returncode != 0


def test_when_as_many_lines_are_run_as_the_floor_asks_for_coverage_passes(
    cmake_project,
):
    # Most of the header's lines run, so it is well over half.
    project = widget_project(cmake_project, "SOCPUPPET_COVERAGE_CPP_FLOOR=50")

    result = project.build("coverage")

    assert result.returncode == 0, result.stdout


def test_counters_left_by_a_program_run_before_do_not_count(cmake_project):
    # A second program runs the line the test misses, but ctest does not
    # run it. Here it is run by hand first, as a developer might.
    project = cmake_project(
        {
            "src/widgets/widget.h": WIDGET_HEADER,
            "vendor/vendor.h": VENDOR_HEADER,
            "tests/widget_test.cpp": WIDGET_TEST,
            "tests/runs_every_line.cpp": """\
#include "widgets/widget.h"

int main() { return AtMostTen(11) - 10 + AtMostTen(0); }
""",
        },
        CMAKE_LISTS
        + "add_executable(runs_every_line tests/runs_every_line.cpp)\n"
        "target_include_directories(runs_every_line PRIVATE src)\n"
        "socpuppet_dev_checks(runs_every_line)\n",
    )
    project.configure(
        "SOCPUPPET_COVERAGE=ON", "SOCPUPPET_COVERAGE_CPP_FLOOR=100"
    )
    project.build("runs_every_line")
    project.run("runs_every_line")

    result = project.build("coverage")

    assert result.returncode != 0


def test_a_python_line_run_only_in_a_child_process_counts_as_run(cmake_project):
    project = cmake_project(
        {
            "python/widgets.py": """\
def in_this_process():
    return 1


def in_a_child_process():
    return 2
""",
            "tests/test_widgets.py": """\
import subprocess
import sys

import widgets


def test_calls_one_function_here_and_the_other_in_a_child_process():
    widgets.in_this_process()
    subprocess.run(
        [sys.executable, "-c", "import widgets; widgets.in_a_child_process()"],
        check=True,
    )
""",
        },
        "enable_testing()\n"
        "add_test(NAME pytest\n"
        "  COMMAND ${SOCPUPPET_TEST_PYTHON} -m pytest tests\n"
        "  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})\n"
        "set_tests_properties(pytest PROPERTIES\n"
        "  ENVIRONMENT PYTHONPATH=${PROJECT_SOURCE_DIR}/python)\n",
    )
    # Every line of widgets.py runs, but only if the child process counts.
    configured = project.configure(
        "SOCPUPPET_COVERAGE=ON", "SOCPUPPET_COVERAGE_PYTHON_FLOOR=100"
    )
    assert configured.returncode == 0, configured.stdout

    result = project.build("coverage")

    assert result.returncode == 0, result.stdout


def reported_files(output):
    """The files in the C++ report's table.

    The table has a header row starting "File" and ends with a TOTAL row.
    """
    lines = output.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("File "))
    last = next(i for i, line in enumerate(lines) if line.startswith("TOTAL"))
    rows = [
        line for line in lines[first + 1 : last] if not line.startswith("-")
    ]
    return [row.split()[0] for row in rows]
