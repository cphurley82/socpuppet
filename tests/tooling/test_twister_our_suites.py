"""socpuppet's own Zephyr applications and tests, as twister finds them.

🎓 A directory is a suite to twister when it has a `testcase.yaml`: which
boards to build the application for, and how to judge what it prints. One
with no such file is built by `firmware/build.sh` and never judged by
twister, however many tests are in it.

Ours are under `firmware/` and under the Zephyr module's `tests/`.
"""

import pathlib

import jsonschema
import yaml
from twister_files import directory_of, suites_of_the_list

from conftest import REPO

#: Where our own Zephyr applications are.
OURS = (REPO / "firmware", REPO / "python/socpuppet/zephyr_module/tests")


def test_every_zephyr_application_of_ours_is_a_suite():
    not_a_suite = [
        named(application)
        for application in applications()
        if not (application / "testcase.yaml").is_file()
    ]

    assert not_a_suite == []


def test_every_suite_of_ours_is_one_twisters_schema_accepts(zephyr_tree):
    schema = yaml.safe_load(
        (
            zephyr_tree / "scripts/schemas/twister/testsuite-schema.yaml"
        ).read_text()
    )
    validator = jsonschema.Draft202012Validator(schema)

    complaints = {
        named(suite): wrong
        for suite, said in suites().items()
        if (wrong := [each.message for each in validator.iter_errors(said)])
    }

    assert complaints == {}


def test_every_scenario_of_ours_says_which_boards_it_is_for():
    # A scenario that does not say is built for every board twister is
    # asked about, and ours are each written for particular hardware.
    saying_nothing = [
        scenario
        for scenario, boards in boards_of_each_scenario().items()
        if not boards
    ]

    assert saying_nothing == []


def test_every_scenario_of_ours_is_for_boards_the_module_has():
    # Twister says so too, when it is run. This says so in a second, and
    # where there is no Zephyr.
    for_boards_there_are_not = {
        scenario: sorted(boards - set(boards_of_the_module()))
        for scenario, boards in boards_of_each_scenario().items()
        if boards - set(boards_of_the_module())
    }

    assert for_boards_there_are_not == {}


def test_every_suite_of_ours_is_in_the_list_the_run_is_made_from():
    # Zephyr's own lines of the list are somewhere that is not here.
    listed = [
        directory_of(suite, zephyr_tree=pathlib.Path("/zephyr"))
        for suite in suites_of_the_list()
    ]

    not_run = [
        named(suite)
        for suite in suites()
        if not any(suite.is_relative_to(directory) for directory in listed)
    ]

    assert not_run == []


def suites():
    """What each `testcase.yaml` of ours says, by its file."""
    return {
        file: yaml.safe_load(file.read_text())
        for root in OURS
        for file in sorted(root.rglob("testcase.yaml"))
    }


def boards_of_each_scenario():
    """The boards each scenario of ours is allowed on, by its file and name.

    As twister reads them: what a suite says for all its scenarios, under
    `common`, and what the scenario adds.
    """
    return {
        (named(file), scenario): allowed(suite.get("common")) | allowed(said)
        for file, suite in suites().items()
        for scenario, said in suite["tests"].items()
    }


def allowed(said):
    """The boards a `platform_allow` names, which may be one, as a string."""
    boards = (said or {}).get("platform_allow", [])
    return {boards} if isinstance(boards, str) else set(boards)


def boards_of_the_module():
    """The boards socpuppet's Zephyr module has, by their directories."""
    boards = REPO / "python/socpuppet/zephyr_module/boards/socpuppet"
    return [each.parent.name for each in boards.glob("*/board.yml")]


def applications():
    """Each directory of ours that is a Zephyr application.

    An application's `CMakeLists.txt` asks for Zephyr. The boot ROM's does
    not: it is not Zephyr.
    """
    return sorted(
        project.parent
        for root in OURS
        for project in root.rglob("CMakeLists.txt")
        if "find_package(Zephyr" in project.read_text()
    )


def named(path):
    """A path as the repository names it."""
    return str(path.relative_to(REPO))
