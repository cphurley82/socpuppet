"""The two lists firmware/twister.sh runs twister from.

`firmware/twister-suites.txt` names the suites of the board-compliance run,
and `firmware/twister-quarantine.yaml` what is left out of them, and why.
Both name things in Zephyr's tree, which `firmware/build.sh` fetches into
build/firmware, so these tests are skipped where it has not been run.
"""

import os
import re

import jsonschema
import pytest
import yaml

from conftest import REPO

SUITES = REPO / "firmware/twister-suites.txt"
QUARANTINE = REPO / "firmware/twister-quarantine.yaml"


@pytest.fixture
def zephyr_tree():
    """Zephyr's own sources, where `firmware/build.sh` fetched them."""
    firmware = os.environ.get("SOCPUPPET_FIRMWARE_DIR", REPO / "build/firmware")
    tree = REPO / firmware / "zephyr"
    if not tree.is_dir():
        pytest.skip(
            f"There is no {tree}. `firmware/build.sh` fetches Zephyr, which "
            "takes a few minutes the first time."
        )
    return tree


def test_every_suite_of_the_list_is_a_directory_with_a_suite_in_it(zephyr_tree):
    without_one = [
        suite
        for suite in suites_of_the_list()
        if not suite_files(suite, zephyr_tree)
    ]

    assert without_one == []


def test_the_quarantine_list_is_one_twisters_schema_accepts(zephyr_tree):
    schema = yaml.safe_load(
        (
            zephyr_tree / "scripts/schemas/twister/quarantine-schema.yaml"
        ).read_text()
    )
    validator = jsonschema.Draft202012Validator(schema)

    complaints = [each.message for each in validator.iter_errors(quarantined())]

    assert complaints == []


def test_every_entry_of_the_quarantine_list_says_why():
    # Twister copies the comment into its reports, which is where somebody
    # asks why a suite was not run.
    without_a_reason = [
        entry for entry in quarantined() if not entry.get("comment", "").strip()
    ]

    assert without_a_reason == []


def test_every_scenario_the_quarantine_list_names_is_one_the_run_has(
    zephyr_tree,
):
    # An entry for a scenario that has been renamed, or whose suite has left
    # the list, leaves nothing out, and nothing would say so.
    scenarios = scenarios_of_the_run(zephyr_tree)
    patterns = [
        pattern for entry in quarantined() for pattern in entry["scenarios"]
    ]

    matching_nothing = [
        pattern
        for pattern in patterns
        if not any(re.fullmatch(pattern, each) for each in scenarios)
    ]

    assert matching_nothing == []


def suites_of_the_list():
    """The directory each line of the list names, without the line's flags."""
    return [
        line.split()[0]
        for line in SUITES.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def suite_files(suite, zephyr_tree):
    """The files under a suite's directory that describe its scenarios.

    The directory is Zephyr's, or this repository's if it starts with
    firmware/ or python/, as firmware/twister.sh takes it.
    """
    ours = suite.startswith(("firmware/", "python/"))
    directory = (REPO if ours else zephyr_tree) / suite
    return [
        file
        for name in ("testcase.yaml", "sample.yaml")
        for file in directory.rglob(name)
    ]


def scenarios_of_the_run(zephyr_tree):
    """The name of every scenario of every suite of the list."""
    return {
        scenario
        for suite in suites_of_the_list()
        for file in suite_files(suite, zephyr_tree)
        for scenario in yaml.safe_load(file.read_text())["tests"]
    }


def quarantined():
    """The entries of the quarantine list."""
    return yaml.safe_load(QUARANTINE.read_text())
