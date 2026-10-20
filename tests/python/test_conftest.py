"""The markers of this directory's conftest.py that follow QBox's CPU.

`not_on_qbox` skips a test when SOCPUPPET_CPU is qbox_cpu, and
`only_on_qbox` when it is not. A `platform` test runs in a process of its
own (`socpuppet.pytest_plugin`), and one that is skipped needs none. These
tests run a scratch pytest session with the conftest.py in it.
"""

import textwrap
from pathlib import Path

import pytest

import socpuppet

CONFTEST = Path(__file__).with_name("conftest.py")


@pytest.fixture
def session(pytester, monkeypatch):
    """A scratch pytest session with this directory's conftest.py."""
    monkeypatch.setenv(
        "PYTHONPATH", str(Path(socpuppet.__file__).parent.parent)
    )
    pytester.makeconftest(CONFTEST.read_text())
    return pytester


class TestAPlatformTestMarkedNotOnQbox:
    def test_on_qbox_is_skipped_for_its_reason_with_no_process_of_its_own(
        self, session, monkeypatch
    ):
        monkeypatch.setenv("SOCPUPPET_CPU", "qbox_cpu")
        imports = a_platform_test_marked(session, "not_on_qbox")

        result = session.runpytest_subprocess("-rs")

        result.assert_outcomes(skipped=1)
        result.stdout.fnmatch_lines(["*: on QBox: spam"])
        assert imports.read_text() == "imported\n"


class TestAPlatformTestMarkedOnlyOnQbox:
    def test_off_qbox_is_skipped_for_its_reason_with_no_process_of_its_own(
        self, session, monkeypatch
    ):
        monkeypatch.delenv("SOCPUPPET_CPU", raising=False)
        imports = a_platform_test_marked(session, "only_on_qbox")

        result = session.runpytest_subprocess("-rs")

        result.assert_outcomes(skipped=1)
        result.stdout.fnmatch_lines(["*: not on QBox: spam"])
        assert imports.read_text() == "imported\n"


def a_platform_test_marked(session, marker):
    """A module with one `platform` test marked `marker`, its reason spam.

    Gives the file it adds a line to each time it is imported: once to be
    collected, and again in a process of the test's own, if one is started.
    """
    imports = session.path / "imports"
    session.makepyfile(
        textwrap.dedent(
            f"""
            import pytest

            with open({str(imports)!r}, "a") as log:
                log.write("imported\\n")

            @pytest.mark.{marker}("spam")
            @pytest.mark.platform
            def test_that_is_marked():
                pass
            """
        )
    )
    return imports
