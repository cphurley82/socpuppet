"""cmake/DevChecks.cmake: the `tidy` target, which runs clang-tidy."""


def project_with_header(cmake_project, header):
    """A configured project whose one program includes `widget.h`."""
    project = cmake_project(
        {
            "widget.h": header,
            "program.cpp": '#include "widget.h"\n\nint main() { return 0; }\n',
        },
        "add_executable(program program.cpp)\nsocpuppet_dev_checks(program)\n",
    )
    configured = project.configure("SOCPUPPET_DEVELOPER_MODE=ON")
    assert configured.returncode == 0, configured.stdout
    return project


def test_when_a_header_breaks_a_clang_tidy_check_tidy_fails_and_names_the_check(
    cmake_project,
):
    project = project_with_header(
        cmake_project,
        """\
#ifndef WIDGET_H_
#define WIDGET_H_

inline int* Nothing() { return 0; }

#endif  // WIDGET_H_
""",
    )

    result = project.build("tidy")

    assert result.returncode != 0
    assert "widget.h:4" in result.stdout
    assert "modernize-use-nullptr" in result.stdout


def test_when_a_clean_header_uses_the_standard_library_tidy_passes(
    cmake_project,
):
    project = project_with_header(
        cmake_project,
        """\
#ifndef WIDGET_H_
#define WIDGET_H_

#include <vector>

inline std::vector<int> Nothing() { return {}; }

#endif  // WIDGET_H_
""",
    )

    result = project.build("tidy")

    assert result.returncode == 0, result.stdout
