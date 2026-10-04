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

            @pytest.mark.platform
            def test_one_platform():
                platform = socpuppet.Platform(writes=[(0x10, 1)])
                platform.run()
                assert platform.peek32(0x10) == 1

            @pytest.mark.platform
            def test_another_platform():
                platform = socpuppet.Platform(writes=[(0x20, 2)])
                platform.run()
                assert platform.peek32(0x20) == 2
            """
        )

        result = session_with_socpuppet.runpytest_subprocess()

        result.assert_outcomes(passed=2)
