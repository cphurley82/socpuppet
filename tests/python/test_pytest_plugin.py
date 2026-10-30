import importlib.metadata
import platform
from pathlib import Path

import pytest

import socpuppet
from socpuppet import pytest_plugin


@pytest.fixture
def session_with_socpuppet(pytester, monkeypatch):
    """A scratch pytest session that can import socpuppet and uses its plugin."""
    monkeypatch.setenv(
        "PYTHONPATH", str(Path(socpuppet.__file__).parent.parent)
    )
    pytester.makeconftest('pytest_plugins = ["socpuppet.pytest_plugin"]')
    return pytester


class TestWhenSeveralPlatformTestsRunInOneSession:
    def test_each_one_passes(self, session_with_socpuppet):
        session_with_socpuppet.makepyfile(
            """
            import pytest
            import socpuppet

            def build_a_platform():
                platform = socpuppet.Platform()
                cpu = platform.add("cpu", socpuppet.ScriptedBusMaster())
                ram = platform.add("ram", socpuppet.Memory(size=0x100))
                platform.connect(cpu.socket, ram.socket)
                platform.build()

            @pytest.mark.platform
            def test_one_platform():
                build_a_platform()

            @pytest.mark.platform
            def test_another_platform():
                build_a_platform()
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=2)


class TestWhenAPlatformTestFails:
    def test_the_session_reports_the_failed_assertion(
        self, session_with_socpuppet
    ):
        session_with_socpuppet.makepyfile(
            """
            import pytest

            @pytest.mark.platform
            def test_that_fails():
                assert "puppet" == "muppet"
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(['*assert "puppet" == "muppet"*'])


class TestWhenAPlatformTestSkipsItself:
    def test_the_session_reports_it_as_skipped(self, session_with_socpuppet):
        session_with_socpuppet.makepyfile(
            """
            import pytest

            @pytest.mark.platform
            def test_that_skips():
                pytest.skip("no strings attached")
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(skipped=1)

    def test_the_summary_of_skips_gives_the_reason(
        self, session_with_socpuppet
    ):
        session_with_socpuppet.makepyfile(
            """
            import pytest

            @pytest.mark.platform
            def test_that_skips():
                pytest.skip("no strings attached")
            """
        )

        result = session_with_socpuppet.runpytest_subprocess("-rs")

        result.stdout.fnmatch_lines(["SKIPPED*no strings attached"])


class TestWhenPytestIsStartedFromASubdirectory:
    def test_a_platform_test_there_runs_in_that_directory(
        self, session_with_socpuppet, monkeypatch
    ):
        session_with_socpuppet.makeini(
            "[pytest]"
        )  # pins the rootdir above the subdirectory
        subdirectory = session_with_socpuppet.mkdir("nested")
        subdirectory.joinpath("test_nested.py").write_text(
            "from pathlib import Path\n"
            "import pytest\n"
            "\n"
            "@pytest.mark.platform\n"
            "def test_that_checks_where_it_runs():\n"
            "    assert Path.cwd().name == 'nested'\n"
        )
        monkeypatch.chdir(subdirectory)

        result = session_with_socpuppet.runpytest_subprocess("test_nested.py")

        result.assert_outcomes(passed=1)


class TestWhenAPlatformTestCrashesItsProcess:
    def test_the_session_reports_it_as_failed_and_says_how_the_process_died(
        self, session_with_socpuppet
    ):
        session_with_socpuppet.makepyfile(
            """
            import os
            import pytest

            @pytest.mark.platform
            def test_that_crashes():
                os.abort()
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*process exited with status*SIGABRT*"])


class TestWhenAPlatformTestCrashesItsProcessInWorkersOfXdist:
    def test_the_session_reports_it_as_failed_where_it_used_to_stop(
        self, session_with_socpuppet
    ):
        # ⚠️ xdist sends each report to the session that runs the workers,
        # and a report that held a pytest Mark was more than it could send:
        # the session stopped with an internal error, and the failure that
        # caused the report was never said.
        session_with_socpuppet.makepyfile(
            """
            import os
            import pytest

            @pytest.mark.platform
            def test_that_crashes():
                os.abort()
            """
        )

        result = session_with_socpuppet.runpytest_subprocess("-n", "1")

        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*process exited with status*SIGABRT*"])


class TestWhenAPlatformTestPassesButItsProcessCrashesOnExit:
    def test_the_session_reports_an_error(self, session_with_socpuppet):
        session_with_socpuppet.makepyfile(
            """
            import atexit
            import os
            import pytest

            @pytest.mark.platform
            def test_that_passes_then_crashes():
                atexit.register(os.abort)
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=1, errors=1)


class TestWhenAPlatformTestIsTheLastOneInItsClass:
    def test_the_ordinary_tests_after_it_still_run(
        self, session_with_socpuppet
    ):
        session_with_socpuppet.makepyfile(
            """
            import pytest

            class TestGroup:
                def test_ordinary(self):
                    pass

                @pytest.mark.platform
                def test_platform(self):
                    pass

            def test_ordinary_after_the_class():
                pass
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=3)


class TestWhenTheEnvironmentsOptionsAddATestFileToEveryRun:
    def test_the_added_test_is_reported_once(
        self, session_with_socpuppet, monkeypatch
    ):
        # ⚠️ PYTEST_ADDOPTS reaches the process a platform test runs in, so
        # that process runs the added file as well, and reports it; counted
        # twice, the run would say 3 passed.
        session_with_socpuppet.makepyfile(
            test_platform="""
            import pytest

            @pytest.mark.platform
            def test_on_a_platform():
                pass
            """,
            test_added="""
            def test_added():
                pass
            """,
        )
        monkeypatch.setenv("PYTEST_ADDOPTS", "test_added.py")

        result = session_with_socpuppet.runpytest_subprocess("test_platform.py")

        result.assert_outcomes(passed=2)


class TestWhenAPlatformTestAsksForATemporaryDirectory:
    def test_it_is_inside_the_sessions_own(self, session_with_socpuppet):
        # Its process then has a temporary directory of its own to clear
        # away, and leaves alone those that other sessions left behind.
        sessions_own = session_with_socpuppet.path / "sessions-own"
        session_with_socpuppet.makepyfile(
            f"""
            from pathlib import Path
            import pytest

            @pytest.mark.platform
            def test_that_checks_where_its_directory_is(tmp_path):
                assert tmp_path.is_relative_to(Path({str(sessions_own)!r}))
            """
        )

        result = session_with_socpuppet.runpytest_subprocess(
            f"--basetemp={sessions_own}"
        )

        result.assert_outcomes(passed=1)


class TestWhenAPlatformTestRunsAfterOneThatWroteToItsTemporaryDirectory:
    def test_what_the_earlier_test_wrote_is_still_there(
        self, session_with_socpuppet
    ):
        session_with_socpuppet.makepyfile(
            """
            import pytest

            left_behind = []

            def test_that_leaves_a_file(tmp_path):
                (tmp_path / "spam").write_text("eggs")
                left_behind.append(tmp_path / "spam")

            @pytest.mark.platform
            def test_on_a_platform(tmp_path):
                pass

            def test_that_looks_for_the_file():
                assert left_behind[0].read_text() == "eggs"
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=3)


class TestWhenAPlatformTestRunsForLongerThanTheTimeout:
    @pytest.fixture
    def result(self, session_with_socpuppet):
        # The clock starts with the test, not with its process, so the
        # shortest limit will do however slowly the process starts.
        session_with_socpuppet.makeini(
            "[pytest]\nsocpuppet_platform_timeout = 1\n"
        )
        session_with_socpuppet.makepyfile(
            """
            import time
            import pytest

            @pytest.mark.platform
            def test_that_never_ends():
                time.sleep(60)

            def test_after_it():
                pass
            """
        )
        return session_with_socpuppet.runpytest_subprocess()

    def test_it_is_stopped_and_reported_as_failed(self, result):
        result.assert_outcomes(failed=1, passed=1)

    def test_the_failure_names_the_setting_that_raises_the_limit(self, result):
        result.stdout.fnmatch_lines(
            ["*longer than 1 second *socpuppet_platform_timeout*"]
        )

    def test_the_failure_shows_where_the_test_was(self, result):
        result.stdout.fnmatch_lines(["*File *, line * in test_that_never_ends"])


class TestWhenAPlatformTestsProcessIsSlowToStart:
    def test_the_test_still_has_the_whole_limit(self, session_with_socpuppet):
        # A machine busy with a whole CI run can take seconds to start an
        # interpreter and collect, and none of that is the test's. Starting
        # takes longer than the whole limit here, and the test is instant,
        # so it passes only if the clock starts with the test.
        a_session_slow_to_start(session_with_socpuppet, seconds=3)
        session_with_socpuppet.makeini(
            "[pytest]\nsocpuppet_platform_timeout = 2\n"
        )
        session_with_socpuppet.makepyfile(
            """
            import pytest

            @pytest.mark.platform
            def test_that_is_quick():
                pass
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=1)


def a_session_slow_to_start(session, seconds):
    """Every pytest started in the session spends `seconds` collecting.

    The session's own pytest too, not only a test's process, so the test
    pays the wait twice.
    """
    session.makeconftest(
        f"""
        import time

        pytest_plugins = ["socpuppet.pytest_plugin"]

        time.sleep({seconds})
        """
    )


class TestWhenNobodySetsTheTimeout:
    @pytest.mark.parametrize(
        ("system", "machine", "minutes"),
        [
            ("Linux", "x86_64", 15),
            ("Darwin", "arm64", 15),
            ("Darwin", "x86_64", 45),
        ],
    )
    def test_the_platform_limit_is_fifteen_minutes_and_three_times_that_on_an_intel_mac(
        self, pytester, monkeypatch, system, machine, minutes
    ):
        # A boot to a prompt takes about 90 s on a free Intel Mac, more than
        # 300 on one building besides with a test worker on every core, and
        # more than 900 on GitHub's, whose boots run four at once.
        monkeypatch.setattr(platform, "system", lambda: system)
        monkeypatch.setattr(platform, "machine", lambda: machine)

        config = pytester.parseconfig("-p", "socpuppet.pytest_plugin")

        limit = config.getini("socpuppet_platform_timeout")
        assert float(limit) == minutes * 60


class TestWhenAPlatformClassSharesOneProcess:
    def test_its_tests_share_one_class_fixture(self, session_with_socpuppet):
        made_in = a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="pass",
            test_eggs="pass",
            test_ham="pass",
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=3)
        assert len(made_in.read_text().split()) == 1

    def test_a_failure_is_reported_for_its_own_test_alone(
        self, session_with_socpuppet
    ):
        a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="pass",
            test_that_fails='assert "puppet" == "muppet"',
            test_eggs="pass",
        )

        result = session_with_socpuppet.runpytest_subprocess("-v")

        result.assert_outcomes(passed=2, failed=1)
        result.stdout.fnmatch_lines(["*test_that_fails FAILED*"])

    def test_a_test_of_it_left_out_of_the_session_does_not_run(
        self, session_with_socpuppet
    ):
        ran = session_with_socpuppet.path / "left_out_ran"
        a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="pass",
            test_left_out=f"open({str(ran)!r}, 'w').close()",
            test_eggs="pass",
        )

        result = session_with_socpuppet.runpytest_subprocess(
            "-k", "not test_left_out"
        )

        result.assert_outcomes(passed=2, deselected=1)
        assert not ran.exists()

    def test_each_of_its_tests_has_the_limit_of_its_own(
        self, session_with_socpuppet
    ):
        # Together they run past the limit; each alone stays well inside it.
        session_with_socpuppet.makeini(
            "[pytest]\nsocpuppet_platform_timeout = 3\n"
        )
        a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="import time; time.sleep(2)",
            test_eggs="import time; time.sleep(2)",
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=2)

    def test_a_crash_fails_its_test_and_errs_the_ones_it_never_started(
        self, session_with_socpuppet
    ):
        a_class_sharing_one_process(
            session_with_socpuppet,
            test_before_the_crash="pass",
            test_that_crashes="os.abort()",
            test_never_started="pass",
        )

        result = session_with_socpuppet.runpytest_subprocess("-v")

        result.assert_outcomes(passed=1, failed=1, errors=1)
        result.stdout.fnmatch_lines(
            [
                "*test_before_the_crash PASSED*",
                "*test_that_crashes FAILED*",
                "*test_never_started ERROR*",
            ]
        )
        result.stdout.fnmatch_lines(
            ["*Never ran: the class's process died during*test_that_crashes*"]
        )

    def test_under_xdist_its_tests_still_share_one_process(
        self, session_with_socpuppet
    ):
        made_in = a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="pass",
            test_eggs="pass",
            test_ham="pass",
        )

        result = session_with_socpuppet.runpytest_subprocess(
            "-n", "2", "--dist", "loadscope"
        )

        result.assert_outcomes(passed=3)
        assert len(made_in.read_text().split()) == 1

    def test_under_xdists_loadgroup_its_tests_still_share_one_process(
        self, session_with_socpuppet
    ):
        # 💡 Grouped by the plugin, so that the tests of other classes,
        # each a boot of its own, are handed out one at a time.
        made_in = a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="pass",
            test_eggs="pass",
            test_ham="pass",
        )

        result = session_with_socpuppet.runpytest_subprocess(
            "-n", "2", "--dist", "loadgroup"
        )

        result.assert_outcomes(passed=3)
        assert len(made_in.read_text().split()) == 1

    @pytest.mark.parametrize(
        "handed_out",
        [[], ["--dist", "worksteal"]],
        ids=["load, the default", "worksteal"],
    )
    def test_under_xdists_load_or_worksteal_its_tests_fail_at_setup_and_say_to_use_loadgroup(
        self, session_with_socpuppet, handed_out
    ):
        # 💡 Both give a class's tests to whichever worker is free, and
        # each worker would boot the class again.
        made_in = a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="pass",
            test_eggs="pass",
            test_ham="pass",
        )

        result = session_with_socpuppet.runpytest_subprocess(
            "-n", "2", *handed_out
        )

        result.assert_outcomes(errors=3)
        assert not made_in.exists()
        result.stdout.fnmatch_lines(["*--dist loadgroup*"])

    def test_its_tests_share_a_process_for_each_parameter_of_its_fixture(
        self, session_with_socpuppet
    ):
        made_in = session_with_socpuppet.path / "made_in"
        session_with_socpuppet.makepyfile(
            f"""
import os
import pytest

@pytest.fixture(scope="class", params=["spam", "eggs"])
def board(request):
    with open({str(made_in)!r}, "a") as log:
        log.write(f"{{request.param}} {{os.getpid()}}\\n")

@pytest.mark.platform(scope="class")
class TestSharingOneProcessForEachBoard:
    def test_one(self, board):
        pass

    def test_another(self, board):
        pass
"""
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=4)
        made = [line.split() for line in made_in.read_text().splitlines()]
        assert sorted(param for param, _ in made) == ["eggs", "spam"]
        assert len({pid for _, pid in made}) == 2

    def test_the_ordinary_tests_after_it_still_run(
        self, session_with_socpuppet
    ):
        a_class_sharing_one_process(
            session_with_socpuppet, test_spam="pass", test_eggs="pass"
        )
        session_with_socpuppet.makepyfile(
            test_after="def test_ordinary_after_the_class():\n    pass\n"
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=3)


def a_class_sharing_one_process(session, **bodies):
    """A class of `platform(scope="class")` tests: a body for each name.

    Its class fixture writes the id of the process it is made in to a file
    of the session's, which this gives back.
    """
    made_in = session.path / "made_in"
    tests = "".join(
        f"""
    def {name}(self, board):
        {body}
"""
        for name, body in bodies.items()
    )
    session.makepyfile(
        f"""
import os
import pytest

@pytest.fixture(scope="class")
def board():
    with open({str(made_in)!r}, "a") as log:
        log.write(f"{{os.getpid()}}\\n")

@pytest.mark.platform(scope="class")
class TestSharingOneProcess:
{tests}
"""
    )
    return made_in


class TestWhenAPlatformTestsProcessDiesOfASignalPythonHasNoNameFor:
    def test_the_status_is_reported_as_the_bare_number(self):
        # Linux's real-time signals are the case: only the first and the
        # last of them have names.
        assert pytest_plugin.describe_exit_status(-1000) == "-1000"


class TestWhenSocpuppetIsInstalledAndNoConftestNamesThePlugin:
    def test_the_platform_marker_is_there_all_the_same(self, pytester):
        try:
            importlib.metadata.distribution("socpuppet")
        except importlib.metadata.PackageNotFoundError:
            pytest.skip(
                "socpuppet is imported from the source tree here. pytest "
                "finds the plugin by itself only when the package is "
                "installed, so the tests of the wheel are where this runs."
            )

        result = pytester.runpytest_subprocess("--markers")

        result.stdout.fnmatch_lines(["@pytest.mark.platform(scope=None):*"])
