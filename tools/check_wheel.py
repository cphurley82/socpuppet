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
    # What is generated from the register maps: for each block, a Python
    # module that the stand-ins and the boards import, and a C header that
    # the Zephyr drivers include. Nothing in a wheel can make them again.
    modules = "socpuppet/regs/"
    headers = "socpuppet/zephyr_module/include/socpuppet/regs/"
    as_python = {
        n.removeprefix(modules).removesuffix(".py")
        for n in names
        if n.startswith(modules) and n.endswith(".py")
    } - {"__init__"}
    as_c = {
        n.removeprefix(headers).removesuffix(".h")
        for n in names
        if n.startswith(headers) and n.endswith(".h")
    }
    if not as_python and not as_c:
        yield (
            "no register map is in the wheel "
            f"(they are generated into {modules} and {headers})"
        )
    for block in sorted(as_c - as_python):
        yield f"{modules}{block}.py is missing (its header is there)"
    for block in sorted(as_python - as_c):
        yield f"{headers}{block}.h is missing (its module is there)"
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
