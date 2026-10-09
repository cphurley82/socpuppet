"""tools/lint.py on the C that is written for Zephyr.

The firmware in `firmware/` and the drivers in socpuppet's Zephyr module
are C, and follow Zephyr's style and not the C++ code's: tabs, braces as
the Linux kernel has them, 100 columns.
"""

import pytest

pytestmark = pytest.mark.usefixtures("zephyrs_style")

ZEPHYR_C = "int answer(void)\n{\n\treturn 42;\n}\n"
GOOGLE_C = "int answer(void) { return 42; }\n"

# Where C for Zephyr lives.
DIRECTORIES = ["firmware/ssd/src", "python/socpuppet/zephyr_module/drivers"]


@pytest.mark.parametrize("directory", DIRECTORIES)
def test_when_c_for_zephyr_is_in_zephyrs_style_lint_passes(
    repo, lint, directory
):
    (repo / directory).mkdir(parents=True)
    (repo / directory / "widget.c").write_text(ZEPHYR_C)

    assert lint().returncode == 0


@pytest.mark.parametrize("directory", DIRECTORIES)
def test_when_c_for_zephyr_is_in_the_cpp_codes_style_lint_fails_and_names_the_file(
    repo, lint, directory
):
    (repo / directory).mkdir(parents=True)
    (repo / directory / "widget.c").write_text(GOOGLE_C)

    result = lint()

    assert result.returncode != 0
    assert "widget.c" in result.stdout


@pytest.mark.parametrize("directory", DIRECTORIES)
def test_when_run_with_fix_c_for_zephyr_is_laid_out_in_zephyrs_style(
    repo, lint, directory
):
    (repo / directory).mkdir(parents=True)
    (repo / directory / "widget.c").write_text(GOOGLE_C)

    lint("--fix")

    assert (repo / directory / "widget.c").read_text() == ZEPHYR_C


# A header guard in the C++ code spells the header's path from src/. A
# header for Zephyr is not under src/, and is named as Zephyr names its own.
@pytest.mark.parametrize("directory", DIRECTORIES)
def test_when_a_header_for_zephyr_has_a_guard_of_its_own_choosing_lint_passes(
    repo, lint, directory
):
    (repo / directory).mkdir(parents=True)
    (repo / directory / "widget.h").write_text(
        "#ifndef WIDGET_H_\n"
        "#define WIDGET_H_\n"
        "\n"
        "int answer(void);\n"
        "\n"
        "#endif /* WIDGET_H_ */\n"
    )

    assert lint().returncode == 0
