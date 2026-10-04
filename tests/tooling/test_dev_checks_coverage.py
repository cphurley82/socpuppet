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
