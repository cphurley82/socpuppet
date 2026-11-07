import importlib.metadata
import os
import platform
import shutil
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
        return a_test_that_runs_out_of_time(session_with_socpuppet)

    def test_it_is_stopped_and_reported_as_failed(self, result):
        result.assert_outcomes(failed=1, passed=1)

    def test_the_failure_names_the_setting_that_raises_the_limit(self, result):
        result.stdout.fnmatch_lines(
            ["*longer than 1 second *socpuppet_platform_timeout*"]
        )

    def test_the_failure_shows_where_the_test_was(self, result):
        result.stdout.fnmatch_lines(
            ["*File *, line * in test_that_runs_out_of_time"]
        )

    def test_the_failure_shows_each_threads_native_stack(self, result):
        skip_unless_a_debugger_can_attach(result)
        # Both threads sleep, and the C library's sleep is in each stack:
        # `nanosleep` on a Mac, `clock_nanosleep` on Linux. Each stack has
        # a heading, lldb's `thread #2` and gdb's `Thread 2 (...)`.
        result.stdout.fnmatch_lines(
            [
                "*Every thread's native stack*",
                *["*hread*", "*nanosleep*"] * 2,
            ]
        )


def a_test_that_runs_out_of_time(session, seconds=60):
    """Run a platform test that sleeps in two threads, past a 1 s limit.

    Each sleeps for `seconds`. A test after it, which is not a platform
    test, passes.
    """
    # The clock starts with the test, not with its process, so the
    # shortest limit will do however slowly the process starts.
    session.makeini("[pytest]\nsocpuppet_platform_timeout = 1\n")
    session.makepyfile(
        f"""
        import threading
        import time
        import pytest

        @pytest.mark.platform
        def test_that_runs_out_of_time():
            threading.Thread(
                target=time.sleep, args=({seconds},), daemon=True
            ).start()
            time.sleep({seconds})

        def test_after_it():
            pass
        """
    )
    return session.runpytest_subprocess()


def skip_unless_a_debugger_can_attach(result):
    """Skip a test of native stacks where none could be taken.

    On a machine with no debugger, or a Mac that keeps lldb from attaching
    to a process it did not start. On Linux the plugin lets gdb attach, so
    a refusal there is a failure.
    """
    debugger = pytest_plugin.native_debugger()
    if shutil.which(debugger) is None:
        pytest.skip(f"{debugger} is not installed here.")
    if debugger == "lldb" and "error: attach failed" in result.stdout.str():
        pytest.skip(
            "lldb may not attach to a process here: "
            "`sudo DevToolsSecurity -enable` lets it."
        )


class TestWhenAPlatformTestRunsOutOfTimeWhereThereIsNoDebugger:
    @pytest.fixture
    def result(self, session_with_socpuppet, monkeypatch):
        # Python is started by its full path, so nothing else is needed.
        monkeypatch.setenv("PATH", str(session_with_socpuppet.mkdir("empty")))
        return a_test_that_runs_out_of_time(session_with_socpuppet)

    def test_the_failure_says_which_debugger_to_install(self, result):
        result.stdout.fnmatch_lines(
            [f"*Install {pytest_plugin.native_debugger()}*"]
        )

    def test_the_failure_still_shows_where_the_test_was(self, result):
        result.stdout.fnmatch_lines(
            ["*File *, line * in test_that_runs_out_of_time"]
        )


class TestWhenAPlatformTestsProcessIsStoppedWhenItRunsOutOfTime:
    def test_the_failure_still_shows_where_the_test_was(
        self, session_with_socpuppet, monkeypatch
    ):
        # A debugger's attach stops the process too, and one that lets go
        # can leave it so. No debugger here, so only the test stops it.
        monkeypatch.setenv("PATH", str(session_with_socpuppet.mkdir("empty")))
        session_with_socpuppet.makeini(
            "[pytest]\nsocpuppet_platform_timeout = 1\n"
        )
        session_with_socpuppet.makepyfile(
            """
            import os
            import signal
            import pytest

            @pytest.mark.platform
            def test_that_stops_itself():
                os.kill(os.getpid(), signal.SIGSTOP)
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.stdout.fnmatch_lines(
            ["*File *, line * in test_that_stops_itself"]
        )


class TestWhenTheDebuggerCannotAttachToATestThatRanOutOfTime:
    @pytest.fixture
    def result(self, session_with_socpuppet, monkeypatch):
        a_debugger_on_the_path(
            session_with_socpuppet,
            monkeypatch,
            'echo "error: attach failed: spam" >&2\nexit 1',
        )
        return a_test_that_runs_out_of_time(session_with_socpuppet)

    @pytest.mark.skipif(
        pytest_plugin.native_debugger() != "lldb", reason="lldb is a Mac's"
    )
    def test_on_a_mac_the_failure_says_how_to_let_lldb_attach(self, result):
        result.stdout.fnmatch_lines(["*sudo DevToolsSecurity -enable*"])

    def test_the_failure_quotes_what_the_debugger_said(self, result):
        result.stdout.fnmatch_lines(
            [
                f"*{pytest_plugin.native_debugger()} could not*",
                "*error: attach failed: spam*",
            ]
        )

    def test_the_failure_still_shows_where_the_test_was(self, result):
        result.stdout.fnmatch_lines(
            ["*File *, line * in test_that_runs_out_of_time"]
        )


class TestWhenTheDebuggerFindsNoThreadInATestThatRanOutOfTime:
    @pytest.fixture
    def result(self, session_with_socpuppet, monkeypatch):
        # 🎓 gdb in batch mode exits with its last command's status, and a
        # backtrace of every thread of none, which is what a refused attach
        # leaves it, succeeds.
        a_debugger_on_the_path(
            session_with_socpuppet,
            monkeypatch,
            'echo "ptrace: Operation not permitted."\nexit 0',
        )
        return a_test_that_runs_out_of_time(session_with_socpuppet)

    def test_the_failure_says_it_could_not_and_quotes_it(self, result):
        result.stdout.fnmatch_lines(
            [
                f"*{pytest_plugin.native_debugger()} could not*",
                "*ptrace: Operation not permitted.*",
            ]
        )

    def test_the_failure_still_shows_where_the_test_was(self, result):
        result.stdout.fnmatch_lines(
            ["*File *, line * in test_that_runs_out_of_time"]
        )


class TestWhenTheDebuggerTakesTooLongOverATestThatRanOutOfTime:
    @pytest.fixture
    def result(self, session_with_socpuppet, monkeypatch):
        a_debugger_on_the_path(
            session_with_socpuppet, monkeypatch, "exec sleep 60"
        )
        session_with_socpuppet.makeconftest(
            """
            from socpuppet import pytest_plugin

            pytest_plugins = ["socpuppet.pytest_plugin"]
            pytest_plugin.DEBUGGER_SECONDS = 1
            """
        )
        return a_test_that_runs_out_of_time(session_with_socpuppet)

    def test_it_is_stopped_and_the_failure_says_so(self, result):
        result.stdout.fnmatch_lines(
            [f"*{pytest_plugin.native_debugger()} took longer than 1 second*"]
        )

    def test_the_failure_still_shows_where_the_test_was(self, result):
        result.stdout.fnmatch_lines(
            ["*File *, line * in test_that_runs_out_of_time"]
        )


class TestWhenAPlatformTestThatRanOutOfTimeHandlesTheSignalItself:
    def test_the_failure_says_its_process_did_not_say_where_it_was(
        self, session_with_socpuppet, monkeypatch
    ):
        # No debugger, so the failure comes as soon as the wait is over.
        monkeypatch.setenv("PATH", str(session_with_socpuppet.mkdir("empty")))
        session_with_socpuppet.makeini(
            "[pytest]\nsocpuppet_platform_timeout = 1\n"
        )
        session_with_socpuppet.makepyfile(
            """
            import signal
            import time
            import pytest

            @pytest.mark.platform
            def test_that_keeps_the_signal():
                signal.signal(signal.SIGUSR1, lambda *_: None)
                time.sleep(60)
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.stdout.fnmatch_lines(
            ["*did not say where its Python was*handles SIGUSR1 itself*"]
        )


class TestWhenAPlatformTestThatRanOutOfTimeEndsAsItIsAsked:
    @pytest.fixture
    def result(self, session_with_socpuppet, monkeypatch):
        # The process is gone by the time the debugger would be asked, so
        # there is nothing to attach to. A stand-in debugger that would
        # answer shows whether it was asked at all.
        a_debugger_on_the_path(
            session_with_socpuppet, monkeypatch, 'echo "#0 spam"'
        )
        session_with_socpuppet.makeini(
            "[pytest]\nsocpuppet_platform_timeout = 1\n"
        )
        session_with_socpuppet.makepyfile(
            """
            import os
            import signal
            import time
            import pytest

            @pytest.mark.platform
            def test_that_ends_when_asked():
                signal.signal(signal.SIGUSR1, lambda *_: os._exit(0))
                time.sleep(60)
            """
        )
        return session_with_socpuppet.runpytest_subprocess()

    def test_it_is_reported_as_failed(self, result):
        result.assert_outcomes(failed=1)

    def test_the_failure_says_its_process_ended_first(self, result):
        result.stdout.fnmatch_lines(
            [
                "*did not say where its Python was*process ended*",
                "*process ended before*native stacks*",
            ]
        )

    def test_the_debugger_is_not_asked(self, result):
        result.stdout.no_fnmatch_line("*#0 spam*")


class TestWhenTheDebuggerOutlastsATestThatRanOutOfTime:
    @pytest.fixture
    def result(self, session_with_socpuppet, monkeypatch):
        # The test's time runs out at 1 s, and its sleeps end at 3, while
        # the debugger is still at work, from 1 s to 6. A debugger holds a
        # process only while it is attached, and the sleeps' clock runs on
        # meanwhile: lldb on CI's Intel Mac took over a minute, and the
        # test finished behind its back.
        a_debugger_on_the_path(
            session_with_socpuppet, monkeypatch, "exec sleep 5"
        )
        return a_test_that_runs_out_of_time(session_with_socpuppet, seconds=3)

    def test_it_is_still_reported_as_failed(self, result):
        result.assert_outcomes(failed=1, passed=1)

    def test_the_failure_still_shows_where_the_test_was(self, result):
        result.stdout.fnmatch_lines(
            ["*File *, line * in test_that_runs_out_of_time"]
        )


def a_debugger_on_the_path(session, monkeypatch, script):
    """Put a stand-in for this machine's debugger first on the PATH.

    It is a shell script that does what `script` says, whatever it is
    asked.
    """
    bin_directory = session.mkdir("bin")
    debugger = bin_directory / pytest_plugin.native_debugger()
    debugger.write_text(f"#!/bin/sh\n{script}\n")
    debugger.chmod(0o755)
    monkeypatch.setenv(
        "PATH", f"{bin_directory}{os.pathsep}{os.environ['PATH']}"
    )


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
            ("Linux", "x86_64", 30),
            ("Darwin", "arm64", 30),
            ("Darwin", "x86_64", 90),
        ],
    )
    def test_the_platform_limit_is_thirty_minutes_and_three_times_that_on_an_intel_mac(
        self, pytester, monkeypatch, system, machine, minutes
    ):
        # A boot through UEFI to a prompt takes two minutes on the
        # interpreter on a free machine, up to 770 s on GitHub's Linux
        # runners with a test on every core (one ran past 900), and more
        # than 1600 s on its Intel Macs.
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
        # The last one's limit also covers its process's way out, which on a
        # busy machine takes a second or more, hence the two seconds spare.
        session_with_socpuppet.makeini(
            "[pytest]\nsocpuppet_platform_timeout = 5\n"
        )
        a_class_sharing_one_process(
            session_with_socpuppet,
            test_spam="import time; time.sleep(3)",
            test_eggs="import time; time.sleep(3)",
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
