"""cmake/DevChecks.cmake: the `check_headers` target.

It compiles each header of a header-only library on its own, to show that
the header includes everything it uses.
"""

NEEDS_VECTOR = """\
#ifndef WIDGETS_NEEDS_VECTOR_H_
#define WIDGETS_NEEDS_VECTOR_H_

inline std::vector<int> Nothing() { return {}; }

#endif  // WIDGETS_NEEDS_VECTOR_H_
"""


def test_when_a_header_uses_something_it_does_not_include_check_headers_fails_and_names_it(
    cmake_project,
):
    project = cmake_project(
        {"widgets/needs_vector.h": NEEDS_VECTOR},
        "add_library(widgets INTERFACE)\n"
        "target_sources(widgets INTERFACE\n"
        "  FILE_SET HEADERS FILES widgets/needs_vector.h)\n"
        "socpuppet_check_headers(widgets)\n",
    )
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON")

    result = project.build("check_headers")

    assert result.returncode != 0
    assert "needs_vector.h:4" in result.stdout
