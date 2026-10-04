"""tools/lint.py on C++ sources."""


def test_when_a_cpp_file_is_misformatted_lint_fails_and_names_the_file(repo, lint):
    (repo / "widget.cpp").write_text("int   answer( ){return 42;}\n")

    result = lint()

    assert result.returncode != 0
    assert "widget.cpp" in result.stdout


def test_when_run_with_fix_a_misformatted_cpp_file_then_passes_lint(repo, lint):
    (repo / "widget.cpp").write_text("int   answer( ){return 42;}\n")

    lint("--fix")

    assert lint().returncode == 0


def test_when_run_with_fix_includes_are_grouped_as_related_standard_third_party_project(
    repo, lint
):
    (repo / "widget.cpp").write_text(
        '#include "socpuppet/core/time.h"\n'
        "#include <tlm>\n"
        "#include <vector>\n"
        '#include "widget.h"\n'
        "#include <gtest/gtest.h>\n"
        "#include <cstdint>\n"
        "#include <systemc>\n"
    )

    lint("--fix")

    assert (repo / "widget.cpp").read_text() == (
        '#include "widget.h"\n'
        "\n"
        "#include <cstdint>\n"
        "#include <vector>\n"
        "\n"
        "#include <gtest/gtest.h>\n"
        "#include <systemc>\n"
        "#include <tlm>\n"
        "\n"
        '#include "socpuppet/core/time.h"\n'
    )


def test_when_a_file_has_a_using_directive_lint_fails_and_names_the_line(repo, lint):
    (repo / "widget.cpp").write_text(
        "#include <string>\n"
        "\n"
        "using namespace std;\n"
        "\n"
        'string Greeting() { return "hello"; }\n'
    )

    result = lint()

    assert result.returncode != 0
    assert "widget.cpp:3:" in result.stdout
