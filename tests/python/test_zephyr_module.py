"""The Zephyr module that carries socpuppet's boards, as an installed file."""

import pathlib

from processes import run_socpuppet


class TestWhenTheZephyrModuleCommandIsRun:
    def test_it_prints_a_directory_that_zephyr_can_use_as_a_module(self):
        printed = run_socpuppet("zephyr-module").stdout

        module = pathlib.Path(printed.strip())
        assert (module / "zephyr" / "module.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_host/board.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_ssd/board.yml").is_file()
