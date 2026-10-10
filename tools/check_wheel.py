"""Check that a built wheel is self-contained and holds nothing it should not.

Usage: python tools/check_wheel.py dist/socpuppet-*.whl
"""

import sys
import zipfile


def problems_with(names):
    """Yield what is wrong with a wheel holding the files `names`."""
    # _core.pyi sits next to the extension and describes it to type checkers.
    extensions = [
        n
        for n in names
        if n.startswith("socpuppet/_core.") and not n.endswith(".pyi")
    ]
    if len(extensions) != 1:
        yield (
            "expected exactly one socpuppet/_core extension, "
            f"found {extensions}"
        )
    if not any(n.endswith("licenses/THIRD_PARTY_NOTICES.md") for n in names):
        yield (
            "THIRD_PARTY_NOTICES.md is missing "
            "(the wheel embeds third-party code)"
        )
    # The Zephyr boards are plain files inside the package. A firmware
    # developer who installed the wheel builds against them.
    if (
        not any(n.startswith("socpuppet/zephyr_module/boards/") for n in names)
        or "socpuppet/zephyr_module/zephyr/module.yml" not in names
    ):
        yield (
            "socpuppet/zephyr_module is missing or incomplete "
            "(the Zephyr boards ship inside the package)"
        )
    # What is generated from the register maps: Python modules that the
    # stand-ins and the board descriptions import, and the C headers that
    # the Zephyr drivers include. Nothing in a wheel can make them again.
    if not any(
        n.startswith("socpuppet/regs/") and n.endswith(".py") for n in names
    ):
        yield (
            "socpuppet/regs has no register map in it "
            "(the stand-ins and the boards import them)"
        )
    headers = "socpuppet/zephyr_module/include/socpuppet/regs/"
    if not any(n.startswith(headers) and n.endswith(".h") for n in names):
        yield (
            f"{headers} has no header in it "
            "(the Zephyr drivers include the register maps)"
        )
    # SystemC, SCC and friends are linked statically into _core. Their own
    # headers, libraries and CMake files must not ride along.
    allowed = ("socpuppet/", "socpuppet-")
    for name in names:
        if not name.startswith(allowed):
            yield f"unexpected file outside the package: {name}"


def main(wheel_path):
    """Print the verdict on the wheel at `wheel_path`.

    Returns the exit status.
    """
    with zipfile.ZipFile(wheel_path) as wheel:
        problems = list(problems_with(wheel.namelist()))
    for problem in problems:
        print(f"❌ {problem}")
    if not problems:
        print(f"✅ {wheel_path} looks right")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
