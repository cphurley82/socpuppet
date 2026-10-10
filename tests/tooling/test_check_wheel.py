"""tools/check_wheel.py, which checks what a built wheel holds."""

import zipfile

# What a good wheel holds, as far as the check cares.
GOOD = (
    "socpuppet/_core.cpython-313-darwin.so",
    "socpuppet/_core.pyi",
    "socpuppet/zephyr_module/zephyr/module.yml",
    "socpuppet/zephyr_module/boards/socpuppet/socpuppet_host/board.yml",
    "socpuppet/regs/__init__.py",
    "socpuppet/regs/dma_engine.py",
    "socpuppet/zephyr_module/include/socpuppet/regs/dma_engine.h",
    "socpuppet-0.0.1.dist-info/licenses/THIRD_PARTY_NOTICES.md",
)


def wheel_holding(directory, names):
    """A wheel in `directory` with an empty file for each of `names`."""
    wheel = directory / "socpuppet-0.0.1-cp313-cp313-macosx_11_0_arm64.whl"
    with zipfile.ZipFile(wheel, "w") as contents:
        for name in names:
            contents.writestr(name, "")
    return wheel


def test_when_the_extension_comes_with_its_type_stub_the_wheel_passes(
    tmp_path, check_wheel
):
    assert check_wheel(wheel_holding(tmp_path, GOOD)).returncode == 0


def test_when_the_zephyr_boards_are_missing_the_wheel_is_refused_and_the_output_says_so(
    tmp_path, check_wheel
):
    without_boards = [name for name in GOOD if "zephyr_module" not in name]

    result = check_wheel(wheel_holding(tmp_path, without_boards))

    assert result.returncode != 0
    assert "zephyr_module" in result.stdout


def test_when_a_register_maps_python_module_is_missing_the_wheel_is_refused_and_the_output_names_it(
    tmp_path, check_wheel
):
    # The package's own __init__.py is still there, and is no register map.
    without_the_module = [
        name for name in GOOD if name != "socpuppet/regs/dma_engine.py"
    ]

    result = check_wheel(wheel_holding(tmp_path, without_the_module))

    assert result.returncode != 0
    assert "socpuppet/regs/dma_engine.py" in result.stdout


def test_when_a_register_maps_c_header_is_missing_the_wheel_is_refused_and_the_output_names_it(
    tmp_path, check_wheel
):
    without_the_header = [
        name for name in GOOD if not name.endswith("regs/dma_engine.h")
    ]

    result = check_wheel(wheel_holding(tmp_path, without_the_header))

    assert result.returncode != 0
    assert "include/socpuppet/regs/dma_engine.h" in result.stdout


def test_when_there_is_no_register_map_at_all_the_wheel_is_refused_and_the_output_says_so(
    tmp_path, check_wheel
):
    without_any = [name for name in GOOD if "dma_engine" not in name]

    result = check_wheel(wheel_holding(tmp_path, without_any))

    assert result.returncode != 0
    assert "register map" in result.stdout
