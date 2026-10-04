"""tools/check_wheel.py, which checks what a built wheel holds."""

import zipfile


def test_when_the_extension_comes_with_its_type_stub_the_wheel_passes(
    tmp_path, check_wheel
):
    wheel = tmp_path / "socpuppet-0.0.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as contents:
        for name in (
            "socpuppet/__init__.py",
            "socpuppet/_core.cpython-313-darwin.so",
            "socpuppet/_core.pyi",
            "socpuppet-0.0.1.dist-info/licenses/THIRD_PARTY_NOTICES.md",
        ):
            contents.writestr(name, "")

    assert check_wheel(wheel).returncode == 0
