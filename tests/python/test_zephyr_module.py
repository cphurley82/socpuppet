"""The Zephyr module that carries socpuppet's boards, as an installed file."""

import os
import pathlib
import subprocess
import sys


class TestWhenTheZephyrModuleCommandIsRun:
    def test_it_prints_a_directory_that_zephyr_can_use_as_a_module(self):
        printed = subprocess.run(
            [sys.executable, "-m", "socpuppet", "zephyr-module"],
            env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        module = pathlib.Path(printed.strip())
        assert (module / "zephyr" / "module.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_host/board.yml").is_file()
