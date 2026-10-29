"""CMakePresets.json's test presets: the three tiers of tests.

`fast` is the inner loop, `quick` is what every push runs, and `dev` is
everything, which runs every night (docs/development.md).
"""

import json
import subprocess

from conftest import REPO, _tool


def selected_by(preset):
    """The tests a test preset runs: by name, the command and the labels."""
    shown = subprocess.run(
        [_tool("ctest"), "--preset", preset, "--show-only=json-v1"],
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    assert shown.returncode == 0, shown.stdout
    return {
        test["name"]: (test["command"], labels_of(test))
        for test in json.loads(shown.stdout)["tests"]
    }


def labels_of(test):
    (labels,) = [
        property["value"]
        for property in test.get("properties", [])
        if property["name"] == "LABELS"
    ] or [[]]
    return labels


def marks_chosen_by(command):
    """What a pytest command line's `-m` chooses: the one after `pytest`."""
    options = command[command.index("pytest") :]
    return options[options.index("-m") + 1]


def test_every_test_has_a_label_for_a_preset_to_choose_it_by(dev_tree):
    assert {
        name for name, (_, labels) in selected_by("dev").items() if not labels
    } == set()


def test_fast_runs_the_cpp_tests_and_the_python_tests_that_are_not_long(
    dev_tree,
):
    fast = selected_by("fast")

    assert {
        name for name, (_, labels) in fast.items() if labels != ["cpp"]
    } == {"pytest"}
    assert marks_chosen_by(fast["pytest"][0]) == "not long"


def test_quick_runs_what_fast_does_and_a_boot_of_each_area_lint_tooling_and_examples(
    dev_tree,
):
    fast, quick = selected_by("fast"), selected_by("quick")

    assert fast.keys() <= quick.keys()
    assert {label for _, labels in quick.values() for label in labels} == {
        "cpp",
        "python",
        "boots",
        "tooling",
        "example",
    }
    assert marks_chosen_by(quick["pytest_boots"][0]) == "representative"


def test_dev_runs_what_quick_does_and_every_other_long_test(dev_tree):
    quick, dev = selected_by("quick"), selected_by("dev")

    assert dev.keys() - quick.keys() == {"pytest_long", "example_linux_cable"}
    assert (
        marks_chosen_by(dev["pytest_long"][0]) == "long and not representative"
    )
