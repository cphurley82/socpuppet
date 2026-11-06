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
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON")
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
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON")

    result = project.build("tidy")

    assert result.returncode == 0, result.stdout


def test_when_a_source_is_listed_by_its_full_path_tidy_still_checks_it(
    cmake_project,
):
    project = cmake_project(
        {
            "program.cpp": "int main() {\n  int* nothing = 0;\n  return nothing != 0;\n}\n"
        },
        "add_executable(program ${CMAKE_CURRENT_SOURCE_DIR}/program.cpp)\n"
        "socpuppet_dev_checks(program)\n",
    )
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON")

    result = project.build("tidy")

    assert result.returncode != 0
    assert "program.cpp:2" in result.stdout


def project_including_a_missing_header(cmake_project, *options):
    """A configured project whose one source includes a header not there.

    It also breaks a check, which clang-tidy, unable to compile it, may
    report or not.
    """
    project = cmake_project(
        {
            "program.cpp": (
                '#include "missing.h"\n\n'
                "int* Nothing() { return 0; }\n\n"
                "int main() { return 0; }\n"
            ),
        },
        "add_executable(program program.cpp)\nsocpuppet_dev_checks(program)\n",
    )
    project.configure("SOCPUPPET_DEVELOPER_MODE=ON", *options)
    return project


def test_when_a_source_includes_a_header_that_is_not_there_tidy_fails_naming_it_says_to_configure_again_and_lists_no_finding(
    cmake_project,
):
    project = project_including_a_missing_header(cmake_project)

    result = project.build("tidy")

    assert result.returncode != 0
    assert "'missing.h' file not found" in result.stdout
    assert "configure the tree again" in result.stdout
    assert "modernize-use-nullptr" not in result.stdout


def test_when_the_tree_is_built_with_a_qbox_that_is_gone_tidy_says_to_build_qbox_again(
    cmake_project, tmp_path
):
    project = project_including_a_missing_header(
        cmake_project, f"SOCPUPPET_QBOX_DIR={tmp_path / 'gone'}"
    )

    result = project.build("tidy")

    assert "uv run tools/build_qbox.py" in result.stdout
