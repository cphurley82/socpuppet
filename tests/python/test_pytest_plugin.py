from pathlib import Path

import pytest

import socpuppet


@pytest.fixture
def session_with_socpuppet(pytester, monkeypatch):
    """A scratch pytest session that can import socpuppet and uses its plugin."""
    monkeypatch.setenv("PYTHONPATH", str(Path(socpuppet.__file__).parent.parent))
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
                cpu = platform.add("cpu", socpuppet.ScriptedBusMaster(writes=[]))
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
    def test_the_session_reports_the_failed_assertion(self, session_with_socpuppet):
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


class TestWhenPytestIsStartedFromASubdirectory:
    def test_a_platform_test_there_runs_in_that_directory(self, session_with_socpuppet, monkeypatch):
        session_with_socpuppet.makeini("[pytest]")  # pins the rootdir above the subdirectory
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
    def test_the_ordinary_tests_after_it_still_run(self, session_with_socpuppet):
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
