"""tools/lint.py on C++ sources."""

import re


def test_when_a_cpp_file_is_misformatted_lint_fails_and_names_the_file(
    repo, lint
):
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


def test_when_a_file_has_a_using_directive_lint_fails_and_names_the_line(
    repo, lint
):
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


def test_when_a_header_guard_does_not_spell_the_headers_path_lint_fails_and_says_what_it_should_be(
    repo, lint
):
    header = repo / "src" / "socpuppet" / "core" / "widget.h"
    header.parent.mkdir(parents=True)
    header.write_text(
        "#ifndef WIDGET_H_\n"
        "#define WIDGET_H_\n"
        "\n"
        "int Answer();\n"
        "\n"
        "#endif  // WIDGET_H_\n"
    )

    result = lint()

    assert result.returncode != 0
    # As a whole word: not as the tail of SRC_SOCPUPPET_CORE_WIDGET_H_.
    assert re.search(r"\bSOCPUPPET_CORE_WIDGET_H_\b", result.stdout)


def test_when_includes_are_in_the_order_fix_puts_them_in_lint_passes(
    repo, lint
):
    source = repo / "src" / "socpuppet" / "core" / "widget.cpp"
    source.parent.mkdir(parents=True)
    source.write_text(
        '#include "socpuppet/core/time.h"\n'
        "#include <tlm>\n"
        "#include <vector>\n"
        '#include "socpuppet/core/widget.h"\n'
        "#include <gtest/gtest.h>\n"
        "#include <cstdint>\n"
        "#include <systemc>\n"
    )
    lint("--fix")

    assert lint().returncode == 0


def test_when_a_line_is_80_columns_wide_lint_passes(repo, lint):
    (repo / "widget.cpp").write_text(comment_of_width(80))

    assert lint().returncode == 0


def test_when_a_line_is_81_columns_wide_lint_fails(repo, lint):
    (repo / "widget.cpp").write_text(comment_of_width(81))

    assert lint().returncode != 0


def comment_of_width(columns):
    """A one-line comment made of short words, so it could be wrapped."""
    words = "// " + "a " * 38
    return words + "a" * (columns - len(words)) + "\n"


def test_when_a_concept_inside_a_namespace_wraps_as_fix_leaves_it_lint_passes(
    repo, lint
):
    (repo / "widget.cpp").write_text(
        "#include <concepts>\n"
        "#include <cstddef>\n"
        "\n"
        "namespace widgets {\n"
        "\n"
        "template <typename T>\n"
        # Long enough that the definition starts on a line of its own.
        "concept Widget = std::constructible_from<T, std::size_t, std::size_t> && "
        "requires(T widget) { { widget.size() } -> std::convertible_to<std::size_t>; };\n"
        "\n"
        "}  // namespace widgets\n"
    )
    lint("--fix")

    assert lint().returncode == 0


def test_when_c_headers_are_in_the_order_fix_puts_them_in_lint_passes(
    repo, lint
):
    (repo / "widget.cpp").write_text(
        "#include <string>\n"
        "#include <unistd.h>\n"
        "#include <systemc>\n"
        "#include <stdint.h>\n"
        "#include <sys/stat.h>\n"
    )
    lint("--fix")

    assert lint().returncode == 0
