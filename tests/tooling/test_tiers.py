"""CMakePresets.json's test presets: the three tiers of tests.

`fast` is the inner loop, `quick` is what every push runs, and `dev` is
everything, which runs every night (docs/development.md).
"""

import json
import subprocess

from conftest import REPO, _tool

#: The ctest entries that run pytest, each on its share of the tests.
PYTEST_ENTRIES = ("pytest", "pytest_boots", "pytest_long")


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


def preset(name):
    """A test preset, as CMakePresets.json has it, with what it inherits."""
    presets = json.loads((REPO / "CMakePresets.json").read_text())
    (found,) = [each for each in presets["testPresets"] if each["name"] == name]
    if "inherits" not in found:
        return found
    inherited = preset(found["inherits"])
    return {
        **inherited,
        **found,
        "environment": {
            **inherited.get("environment", {}),
            **found.get("environment", {}),
        },
    }


def not_cpp(selected):
    """The names of the tests chosen that are not C++ tests."""
    return {name for name, (_, labels) in selected.items() if labels != ["cpp"]}


def collected_by(command, *more):
    """The tests a ctest entry's pytest command would run, by their ids."""
    collected = subprocess.run(
        [*command, *more, "--collect-only", "-q", "-n", "0"],
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    assert collected.returncode == 0, collected.stdout
    return {line for line in collected.stdout.splitlines() if "::" in line}


def test_every_test_has_a_label_for_a_preset_to_choose_it_by(dev_tree):
    assert {
        name for name, (_, labels) in selected_by("dev").items() if not labels
    } == set()


def test_fast_runs_the_cpp_tests_and_the_python_tests_that_are_not_long(
    dev_tree,
):
    fast = selected_by("fast")

    assert not_cpp(fast) == {"pytest"}
    command, _ = fast["pytest"]
    assert collected_by(command) & collected_by(command, "-m", "long") == set()


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
    command, _ = quick["pytest_boots"]
    boots = collected_by(command)
    assert boots
    assert boots <= collected_by(command, "-m", "long")


def test_quick_without_boots_runs_all_quick_does_but_the_boots(dev_tree):
    # 💡 An Intel Mac runs it as its quick tier (tools/ci.py). A preset of
    # its own, since ctest takes no -LE beside a preset's filter.
    quick = selected_by("quick")
    without_boots = selected_by("quick-without-boots")

    assert quick.keys() - without_boots.keys() == {"pytest_boots"}
    assert without_boots.keys() <= quick.keys()


def test_dev_runs_what_quick_does_and_every_other_long_test(dev_tree):
    quick, dev = selected_by("quick"), selected_by("dev")

    assert dev.keys() - quick.keys() == {"pytest_long", "example_linux_cable"}
    # Between them the three run every Python test, and none twice.
    runs = [collected_by(dev[name][0]) for name in PYTEST_ENTRIES]
    assert sum(len(each) for each in runs) == len(set().union(*runs))
    assert set().union(*runs) == collected_by(dev["pytest"][0], "-m", "")


def test_qbox_runs_what_dev_does_on_qboxs_hart_but_the_cable_example(
    dev_tree, qbox_tree
):
    # A C++ test of what a build does without QBox's hart has no place in
    # a build with it, so the C++ tests are left out of the comparison.
    dev, qbox = (not_cpp(selected_by(preset)) for preset in ("dev", "qbox"))

    assert dev - qbox == {"example_linux_cable"}


def test_qbox_quick_runs_what_fast_does_and_a_boot_of_each_area_on_qboxs_hart(
    qbox_tree,
):
    qbox_quick = selected_by("qbox-quick")

    assert not_cpp(qbox_quick) == {"pytest", "pytest_boots"}
    assert preset("qbox-quick")["environment"]["SOCPUPPET_CPU"] == "qbox_cpu"
