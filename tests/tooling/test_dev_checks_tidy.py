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


def test_when_a_header_uses_pragma_once_tidy_fails_and_names_the_check(
    cmake_project,
):
    project = project_with_header(
        cmake_project,
        """\
#pragma once

inline int Answer() { return 42; }
""",
    )

    result = project.build("tidy")

    assert result.returncode != 0
    assert "portability-avoid-pragma-once" in result.stdout


def test_when_a_function_is_named_in_snake_case_tidy_fails_and_names_the_line(
    cmake_project,
):
    project = project_with_header(
        cmake_project,
        """\
#ifndef WIDGET_H_
#define WIDGET_H_

inline int twice_the(int number) { return number * 2; }

#endif  // WIDGET_H_
""",
    )

    result = project.build("tidy")

    assert result.returncode != 0
    assert "widget.h:4" in result.stdout
    assert "readability-identifier-naming" in result.stdout


def test_when_a_method_has_a_name_tlm_imposes_tidy_passes(cmake_project):
    project = project_with_header(
        cmake_project,
        """\
#ifndef WIDGET_H_
#define WIDGET_H_

struct Target {
  int last = 0;

  void b_transport(int transaction) { last = transaction; }
};

#endif  // WIDGET_H_
""",
    )

    result = project.build("tidy")

    assert result.returncode == 0, result.stdout


def test_when_a_program_is_compiled_with_a_gcc_only_warning_flag_tidy_passes(
    cmake_project,
):
    project = cmake_project(
        {"program.cpp": "int main() { return 0; }\n"},
        "add_executable(program program.cpp)\n"
        "target_compile_options(program PRIVATE -Wno-interference-size)\n"
        "socpuppet_dev_checks(program)\n",
    )
    configured = project.configure("SOCPUPPET_DEVELOPER_MODE=ON")
    assert configured.returncode == 0, configured.stdout

    result = project.build("tidy")

    assert result.returncode == 0, result.stdout
