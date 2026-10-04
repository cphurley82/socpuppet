import pytest

import socpuppet


@pytest.mark.platform
class TestWhenPythonRunsThePlatform:
    def test_peek_returns_what_the_master_wrote(self):
        platform = socpuppet.Platform(writes=[(0x10, 0xC0FFEE)])

        platform.run()

        assert platform.peek32(0x10) == 0xC0FFEE


@pytest.mark.platform
class TestWhenASecondPlatformIsBuiltInOneProcess:
    def test_the_error_explains_the_one_kernel_rule_and_names_the_marker(self):
        first = socpuppet.Platform(writes=[])
        first.run()

        with pytest.raises(RuntimeError) as error:
            socpuppet.Platform(writes=[])

        assert "only one Platform" in str(error.value)
        assert "SystemC kernel" in str(error.value)
        assert "@pytest.mark.platform" in str(error.value)
