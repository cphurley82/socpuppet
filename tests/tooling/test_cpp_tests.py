"""tests/cpp/CMakeLists.txt: how the C++ tests are registered with CTest."""

import json
from pathlib import Path

from conftest import _run, _tool


def cpp_tests_registered_in(tree):
    """CTest's registration of the tests of the programs in tests/cpp.

    By name: the program's name and the test's properties.
    """
    shown = _run(_tool("ctest"), "--test-dir", str(tree), "--show-only=json-v1")
    assert shown.returncode == 0, shown.stdout
    return {
        test["name"]: (
            Path(test["command"][0]).name,
            {
                property["name"]: property["value"]
                for property in test.get("properties", [])
            },
        )
        for test in json.loads(shown.stdout)["tests"]
        if Path(test["command"][0]).parent == tree / "tests/cpp"
    }


def test_every_cpp_test_is_labelled_cpp_and_times_out_after_two_minutes(
    dev_tree,
):
    tests = cpp_tests_registered_in(dev_tree)

    assert {program for program, _ in tests.values()} >= {
        "unit_tests",
        "kernel_tests",
    }
    assert {
        name
        for name, (_, properties) in tests.items()
        if properties.get("LABELS") != ["cpp"]
        or properties.get("TIMEOUT") != 120
    } == set()
