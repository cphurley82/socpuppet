import pytest

import socpuppet


@pytest.mark.platform
class TestWhenPythonRunsThePlatform:
    def test_peek_returns_what_the_master_wrote(self):
        platform = socpuppet.Platform(writes=[(0x10, 0xC0FFEE)])

        platform.run()

        assert platform.peek32(0x10) == 0xC0FFEE
