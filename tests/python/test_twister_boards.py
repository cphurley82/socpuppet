"""What twister, Zephyr's test runner, reads of socpuppet's boards.

Two files beside each board's `board.yml` in the Zephyr module: a platform
file, which says what the board is, and a `board.cmake`, which says how an
image built for it is run.

⚠️ These tests want more than socpuppet and pytest: a YAML reader and a
JSON Schema validator for the first file, CMake and ninja for the second.
The developer's environment has them (`uv sync`). Where they are missing,
as when the tests are run against an installed wheel, the tests are
skipped.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import textwrap
import threading
from typing import NamedTuple

import pytest

import processes
from cast import ROM_FOR_A_32_BIT_CPU
from riscv_program import a_program_that_says
from socpuppet.pytest_plugin import patience_factor
from zephyr_module import BOARDS, ZEPHYR_MODULE, ram_size

jsonschema = pytest.importorskip("jsonschema")
yaml = pytest.importorskip("yaml")

needs_cmake_and_ninja = pytest.mark.skipif(
    shutil.which("cmake") is None or shutil.which("ninja") is None,
    reason="CMake and ninja are not both installed",
)


class TestWhatTwisterReadsOfEachBoard:
    """🎓 Twister is Zephyr's test runner. It learns what a board is from
    the board's platform file, `<board>.yaml` beside its `board.yml`: its
    architecture, how much memory it has, and what runs an image built for
    it. A board with no such file is one twister has never heard of."""

    @pytest.mark.parametrize("board", BOARDS)
    def test_its_platform_file_is_one_twisters_schema_accepts(
        self, board, zephyr_tree
    ):
        assert (
            twisters_complaints_about(platform_file(board), zephyr_tree) == []
        )

    @pytest.mark.parametrize("board", BOARDS)
    def test_twister_knows_it_by_the_boards_name(self, board):
        assert platform_file(board).get("identifier") == board

    @pytest.mark.parametrize("board", BOARDS)
    def test_it_is_a_simulated_riscv_board_that_socpuppet_runs(self, board):
        # 🎓 `custom` is twister's word for an emulator it knows nothing
        # of: it runs the build's `run` target and reads what is printed.
        # `exec` is the program it looks for before it runs anything, and a
        # board whose program it cannot find is built and never run.
        said = platform_file(board)

        assert {
            name: said.get(name) for name in ("type", "arch", "simulation")
        } == {
            "type": "sim",
            "arch": "riscv",
            "simulation": [{"name": "custom", "exec": "socpuppet"}],
        }

    @pytest.mark.parametrize("board", BOARDS)
    def test_it_has_the_name_the_board_gives_itself(self, board):
        assert platform_file(board).get("name") == full_name(board)

    @pytest.mark.parametrize("board", BOARDS)
    def test_it_is_built_with_the_zephyr_sdks_toolchain(self, board):
        # Twister filters out a board that does not list the toolchain it
        # was told to build with.
        assert "zephyr" in platform_file(board).get("toolchain", ())

    @pytest.mark.parametrize("board", BOARDS)
    def test_it_has_a_watchdog(self, board):
        # A suite says what hardware it `depends_on`, and Zephyr's watchdog
        # test is run only on a board that says it has one.
        assert "watchdog" in platform_file(board).get("supported", ())

    @pytest.mark.parametrize("board", BOARDS)
    def test_its_ram_and_flash_are_the_memory_its_devicetree_has(self, board):
        # In KiB. A suite says the least it needs of each, and twister
        # leaves it out on a board with less. An image for these boards
        # runs where it is loaded, so its code is in the RAM too, and both
        # numbers are the RAM's.
        said = platform_file(board)

        kibibytes = ram_size(board) // 1024
        assert (said.get("ram"), said.get("flash")) == (kibibytes, kibibytes)


def twisters_complaints_about(platform, zephyr_tree):
    """What twister's own schema for a platform file says is wrong with one."""
    schema = yaml.safe_load(
        (
            zephyr_tree / "scripts/schemas/twister/platform-schema.yaml"
        ).read_text()
    )
    validator = jsonschema.Draft202012Validator(schema)
    return [each.message for each in validator.iter_errors(platform)]


@needs_cmake_and_ninja
class TestWhenTheRunTargetOfAnImagesBuildIsBuilt:
    """🎓 Twister runs an image by building the `run` target of the image's
    own build directory, and so does `west build -t run`. What that target
    does is the board's to say, in its `board.cmake`."""

    @pytest.mark.parametrize("board", BOARDS)
    def test_socpuppet_is_told_to_run_the_image_on_that_board(
        self, board, tmp_path
    ):
        build = a_build_for(
            board, tmp_path, socpuppet=WRITES_DOWN_ITS_ARGUMENTS
        )

        build_the_run_target_of(build)

        assert build.what_socpuppet_wrote_down() == [
            "run",
            str(build.image),
            "--board",
            board,
        ]

    def test_it_is_told_of_each_shield_the_image_was_built_with(self, tmp_path):
        build = a_build_for(
            "socpuppet_host",
            tmp_path,
            socpuppet=WRITES_DOWN_ITS_ARGUMENTS,
            shields=("spam", "eggs"),
        )

        build_the_run_target_of(build)

        arguments = build.what_socpuppet_wrote_down()
        assert arguments[arguments.index("--shield") :] == [
            "--shield",
            "spam",
            "--shield",
            "eggs",
        ]

    def test_the_image_is_built_first(self, tmp_path):
        build = a_build_for(
            "socpuppet_ssd", tmp_path, socpuppet=SAYS_WHETHER_ITS_IMAGE_IS_THERE
        )

        printed = build_the_run_target_of(build).stdout

        assert "the image is there" in printed

    def test_the_images_console_is_printed(self, tmp_path, firmware):
        # The whole way: the target, the command and the boot ROM, which
        # the command finds though ninja runs it from the build directory.
        build = a_build_for(
            "socpuppet_ssd",
            tmp_path,
            socpuppet=THE_COMMAND_ITSELF,
            image=a_program_that_says("Lovely spam!\n", tmp_path),
            SOCPUPPET_FIRMWARE_DIR=str(firmware(ROM_FOR_A_32_BIT_CPU).parent),
        )

        printed = build_the_run_target_of(build).stdout

        assert "Lovely spam!" in printed

    def test_the_console_is_heard_while_the_image_still_runs(self, tmp_path):
        # Twister reads the console as it comes, and ends the run when it
        # has read enough. A build tool would rather keep what a command
        # prints until the command is over.
        build = a_build_for(
            "socpuppet_ssd", tmp_path, socpuppet=SAYS_SPAM_AND_WAITS_TO_BE_TOLD
        )
        heard = threading.Event()

        def listen(console):
            for line in console:
                if "Lovely spam!" in line:
                    heard.set()

        with start_the_run_target_of(build) as running:
            listener = threading.Thread(target=listen, args=(running.stdout,))
            listener.start()
            heard_while_it_ran = heard.wait(timeout=10 * patience_factor())
            (build.directory / "told").touch()
            listener.join()

        assert heard_while_it_ran


#: Stand-ins for the command, for what a test asks of the target and not
#: of the command. Each is run in the build directory.
WRITES_DOWN_ITS_ARGUMENTS = '#!/bin/sh\nprintf "%s\\n" "$@" > arguments\n'
SAYS_WHETHER_ITS_IMAGE_IS_THERE = (
    '#!/bin/sh\ntest -e "$2" && echo the image is there\n'
)
#: It gives up waiting after 20 s, so that a test that fails still ends.
SAYS_SPAM_AND_WAITS_TO_BE_TOLD = (
    "#!/bin/sh\n"
    "echo 'Lovely spam!'\n"
    "tries=0\n"
    'while [ ! -e told ] && [ "$tries" -lt 200 ]; do\n'
    "  sleep 0.1\n"
    "  tries=$((tries + 1))\n"
    "done\n"
)
THE_COMMAND_ITSELF = f'#!/bin/sh\nexec "{sys.executable}" -m socpuppet "$@"\n'


class _Build(NamedTuple):
    """A build directory whose `run` target a board's `board.cmake` made."""

    directory: pathlib.Path
    #: Where the image is once it is built.
    image: pathlib.Path
    #: What the build is run with: a `socpuppet` first on its PATH.
    environment: dict[str, str]

    def what_socpuppet_wrote_down(self):
        return (self.directory / "arguments").read_text().splitlines()


def a_build_for(board, tmp_path, *, socpuppet, shields=(), image=None, **extra):
    """A configured build of an image for `board`, as Zephyr would lay it out.

    `socpuppet` is the script the build finds by that name. `image` is the
    file that building the image puts in its place, and `extra` is added to
    the build's environment.

    ⚠️ The project is a stand-in for Zephyr's own build, and has copied
    from it the names a `board.cmake` is given and the order things happen
    in: `board.cmake` is read first (cmake/modules/kernel.cmake), and only
    then does Zephyr's own directory name the target that builds the image
    and make `run` (its CMakeLists.txt). Twister on a real image is what
    says whether Zephyr still does it so.
    """
    source = tmp_path / "source"
    (source / "zephyr").mkdir(parents=True)
    if image is None:
        image = source / "spam.elf"
        image.write_text("spam")
    (source / "CMakeLists.txt").write_text(
        textwrap.dedent(
            f"""\
            cmake_minimum_required(VERSION 3.20)
            project(spam NONE)
            set(BOARD {board})
            set(SHIELD_AS_LIST {";".join(shields)})
            set(APPLICATION_BINARY_DIR ${{CMAKE_BINARY_DIR}})
            set(KERNEL_ELF_NAME zephyr.elf)
            include({ZEPHYR_MODULE}/boards/socpuppet/{board}/board.cmake)
            add_subdirectory(zephyr)
            """
        )
    )
    (source / "zephyr/CMakeLists.txt").write_text(
        textwrap.dedent(
            f"""\
            add_custom_target(the_image COMMAND ${{CMAKE_COMMAND}} -E copy
                              {image} ${{CMAKE_BINARY_DIR}}/zephyr/zephyr.elf)
            set(logical_target_for_zephyr_elf the_image)
            set(logical_target_for_zephyr_elf the_image PARENT_SCOPE)
            list(GET SUPPORTED_EMU_PLATFORMS 0 default_emu)
            add_custom_target(run DEPENDS run_${{default_emu}})
            """
        )
    )
    programs = tmp_path / "bin"
    programs.mkdir()
    (programs / "socpuppet").write_text(socpuppet)
    (programs / "socpuppet").chmod(0o755)
    directory = tmp_path / "build"
    environment = processes.environment(
        PATH=f"{programs}{os.pathsep}{os.environ['PATH']}", **extra
    )
    configured = subprocess.run(
        ["cmake", "-S", source, "-B", directory, "-G", "Ninja"],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert configured.returncode == 0, configured.stdout + configured.stderr
    return _Build(directory, directory / "zephyr/zephyr.elf", environment)


def build_the_run_target_of(build):
    """Build the `run` target, and return the finished process."""
    with start_the_run_target_of(build) as running:
        stdout, stderr = running.communicate()
    assert running.returncode == 0, stdout + stderr
    return subprocess.CompletedProcess(
        running.args, running.returncode, stdout, stderr
    )


def start_the_run_target_of(build):
    """Start building the `run` target, with what it prints piped back."""
    return subprocess.Popen(
        ["cmake", "--build", build.directory, "--target", "run"],
        env=build.environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def full_name(board):
    """What a board calls itself, in the `board.yml` that makes it a board."""
    described = ZEPHYR_MODULE / "boards/socpuppet" / board / "board.yml"
    return yaml.safe_load(described.read_text())["board"]["full_name"]


def platform_file(board):
    """What a board's platform file says."""
    file = ZEPHYR_MODULE / "boards/socpuppet" / board / f"{board}.yaml"
    return yaml.safe_load(file.read_text())
