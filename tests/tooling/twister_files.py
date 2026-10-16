"""The files firmware/twister.py runs twister from, as the tests read them."""

from conftest import REPO

SUITES = REPO / "firmware/twister-suites.txt"


def directory_of(suite, zephyr_tree):
    """Where firmware/twister.py looks for a line's suites (its `resolve`).

    In Zephyr's tree, unless the line is `firmware` or `python`, or under
    one of them: those are this repository's.
    """
    ours = suite.split("/")[0] in ("firmware", "python")
    return (REPO if ours else zephyr_tree) / suite


def suites_of_the_list():
    """The directory each line of the list names, without the line's flags."""
    return [
        line.split()[0]
        for line in SUITES.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
