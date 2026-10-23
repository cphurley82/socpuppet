"""tools/needs.py: what a script needs of this machine, and how it stops.

tools/build_qbox.py, tools/build_pciem.py and tools/pciem_guest.py each
look for the programs they need and stop, naming the packages to install,
without one. What they share is here; what each says is in its own tests.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NEEDS = REPO / "tools" / "needs.py"


@pytest.fixture
def needs():
    """tools/needs.py as a module."""
    spec = importlib.util.spec_from_file_location("needs", NEEDS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestWhenAScriptLooksForWhatItNeeds:
    def test_the_programs_not_on_the_path_are_not_installed_in_the_order_asked(
        self, needs, tmp_path, monkeypatch
    ):
        put_on_the_path(tmp_path, monkeypatch, "spam", "eggs")
        wanted = (
            ("eggs", "eggs"),
            ("ham", "ham-static"),
            ("spam", "spam"),
            ("bacon", "libbacon-dev"),
        )

        assert needs.not_installed(wanted) == [
            ("ham", "ham-static"),
            ("bacon", "libbacon-dev"),
        ]


class TestWhenAScriptStopsWithoutWhatItNeeds:
    def test_the_failure_names_the_programs_and_the_ubuntu_packages(
        self, needs
    ):
        failed = needs.Failed.without(
            "Spam cannot be made", [("ham", "ham-static"), ("eggs", "libeggs")]
        )

        assert str(failed) == (
            "Spam cannot be made without ham eggs.\n"
            "On Ubuntu: sudo apt install ham-static libeggs"
        )

    def test_with_homebrew_formulas_it_also_says_what_a_mac_brews(self, needs):
        failed = needs.Failed.without(
            "Spam cannot be made",
            [("ham", "ham-static", "ham"), ("eggs", "libeggs", "eggs")],
        )

        assert str(failed).endswith("\nOn a Mac: brew install ham eggs")

    def test_it_ends_with_where_to_read_more_when_there_is_somewhere(
        self, needs
    ):
        failed = needs.Failed.without(
            "Spam cannot be made",
            [("ham", "ham-static", "ham")],
            see="docs/setup.md lists every package Spam needs.",
        )

        assert str(failed).endswith(
            "\nOn a Mac: brew install ham\n"
            "docs/setup.md lists every package Spam needs."
        )


def put_on_the_path(directory, monkeypatch, *names):
    """A PATH of `directory` alone, with a program of each name in it."""
    for name in names:
        program = directory / name
        program.write_text("#!/bin/sh\n")
        program.chmod(0o755)
    monkeypatch.setenv("PATH", str(directory))
