"""The markers of this directory's conftest.py that pick what runs.

`not_on_qbox` skips a test when SOCPUPPET_CPU is qbox_cpu, and
`only_on_qbox` when it is not. A `platform` test runs in a process of its
own (`socpuppet.pytest_plugin`), and one that is skipped needs none.
And SOCPUPPET_CPU set to qbox_cpu on a build without
QBox's CPU stops the session before any test, with how to build one. These
tests run a scratch pytest session with the conftest.py in it.
"""

import textwrap
from pathlib import Path

import pytest

import socpuppet
from socpuppet import _core

CONFTEST = Path(__file__).with_name("conftest.py")


@pytest.fixture
def session(pytester, monkeypatch):
    """A scratch pytest session with this directory's conftest.py."""
    monkeypatch.setenv(
        "PYTHONPATH", str(Path(socpuppet.__file__).parent.parent)
    )
    pytester.makeconftest(CONFTEST.read_text())
    return pytester


@pytest.mark.skipif(not _core.has_qbox, reason="this build has no qbox_cpu")
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


@pytest.mark.skipif(_core.has_qbox, reason="this build has qbox_cpu")
class TestASessionAskedForQboxsCpuOnABuildWithoutIt:
    def test_stops_before_any_test_in_one_line_that_says_how_to_build_one(
        self, session, monkeypatch
    ):
        monkeypatch.setenv("SOCPUPPET_CPU", "qbox_cpu")
        two_tests_that_would_pass(session)

        result = session.runpytest_subprocess()

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        assert "passed" not in result.stdout.str()
        [line] = [line for line in result.stderr.lines if "qbox_cpu" in line]
        assert "cmake --build --preset qbox" in line


def two_tests_that_would_pass(session):
    """A module of two tests, either of which would pass, were it run."""
    session.makepyfile(
        textwrap.dedent(
            """
            def test_spam():
                pass

            def test_eggs():
                pass
            """
        )
    )


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
