"""The Zephyr module that carries socpuppet's boards, as an installed file."""

import os
import pathlib
import re
import subprocess
import sys
import textwrap
import threading
from typing import NamedTuple

import jsonschema
import pytest
import yaml

import processes
import socpuppet as sp
from cast import ROM_FOR_A_32_BIT_CPU
from processes import run_socpuppet
from riscv_program import a_program_that_says
from socpuppet.boards.host import UART_SOURCE, host
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd
from socpuppet.components import Aplic
from zephyr_module import (
    BOARDS,
    ZEPHYR_MODULE,
    full_name,
    kconfig_default,
    platform_file,
    ram_size,
    the_identities_of_the_hosts_drive,
)


class TestWhenTheZephyrModuleCommandIsRun:
    def test_it_prints_a_directory_that_zephyr_can_use_as_a_module(self):
        printed = run_socpuppet("zephyr-module").stdout

        module = pathlib.Path(printed.strip())
        assert (module / "zephyr" / "module.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_host/board.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_ssd/board.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_iomgr/board.yml").is_file()


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
            heard_while_it_ran = heard.wait(timeout=10)
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


class TestTheBindingsOfTheZephyrModule:
    """🎓 A binding tells Zephyr what a devicetree node of some compatible
    has in it, and a driver says which compatible it is the driver for.
    Three files have to agree for one device, and nothing in a build says
    so until a driver is quietly left out of an image."""

    def test_every_compatible_of_ours_in_a_devicetree_has_a_binding(self):
        assert our_compatibles_in_the_devicetrees() <= set(bindings())

    def test_every_binding_is_in_a_file_named_after_its_compatible(self):
        assert {
            compatible: binding.stem
            for compatible, binding in bindings().items()
        } == {compatible: compatible for compatible in bindings()}

    def test_every_driver_is_for_a_compatible_that_has_a_binding(self):
        # A driver spells its compatible as a C name: `socpuppet_dma_engine`
        # for "socpuppet,dma-engine". Spelled the same way, every binding's
        # compatible is a name a driver could have.
        spelled_as_c = {re.sub(r"[,-]", "_", name) for name in bindings()}

        assert compatibles_the_drivers_are_for() <= spelled_as_c

    def test_every_bindings_vendor_is_one_zephyr_has_been_told_of(self):
        vendors = {compatible.partition(",")[0] for compatible in bindings()}

        assert vendors <= vendors_zephyr_is_told_of()


class TestTheInterruptNumbersZephyrIsToldOfASocWithAPlic:
    """🎓 With a PLIC, Zephyr numbers interrupts in two levels. The first
    level is the CPU's own inputs, and one of them is the line an interrupt
    controller drives. That controller's sources are the second level, and
    are numbered on from where the first level ends. The SoC's Kconfig says
    where that is, and how many there are, and a board's description says
    the same things its own way."""

    def test_the_second_level_hangs_off_the_input_the_plic_drives(self):
        assert plic_default("2ND_LVL_INTR_00_OFFSET") == (
            the_number_a_cpu_knows_its_plic_by()
        )

    def test_the_second_levels_numbers_start_after_the_first_levels(self):
        # The CPU's inputs are numbered from 0 up to the one the PLIC
        # drives, which is the last of them.
        assert plic_default("2ND_LVL_ISR_TBL_OFFSET") == (
            the_number_a_cpu_knows_its_plic_by() + 1
        )

    def test_an_interrupt_controller_has_room_for_every_source_of_the_plic(
        self,
    ):
        # And for source 0, which means "none".
        assert plic_default("MAX_IRQ_PER_AGGREGATOR") == sp.Plic.SOURCES + 1

    def test_there_are_as_many_interrupts_as_both_levels_have(self):
        assert plic_default("NUM_IRQS") == plic_default(
            "2ND_LVL_ISR_TBL_OFFSET"
        ) + plic_default("MAX_IRQ_PER_AGGREGATOR")


def plic_default(name):
    """The number a SoC with a PLIC gives Zephyr for a Kconfig option."""
    return kconfig_default(name, under="RISCV_HAS_PLIC")


class TestTheInterruptNumbersZephyrIsToldOfASocWithAnImsic:
    """🎓 With an IMSIC there is one level. Zephyr's driver takes a
    message's identity as the interrupt's number, and looks it up in the
    same table as the CPU's own inputs, which have the numbers below 16."""

    def test_there_is_a_number_for_every_identity_and_for_none(self):
        # Identity 0 means "none", and counts as one.
        assert kconfig_default("NUM_IRQS", under="RISCV_IMSIC") == (
            host().imsic.component.identities + 1
        )

    def test_each_identity_of_the_hosts_drive_is_one_zephyr_takes_as_a_message(
        self,
    ):
        # Not a number of one of the CPU's own inputs, which the module's
        # `irq_enable` would take for that input. And below the IMSIC's
        # highest identity: Zephyr's driver turns that one away, though it
        # is one the IMSIC has (docs/upstream.md).
        first = the_first_number_that_is_an_identity()
        highest = host().imsic.component.identities

        for identity in the_identities_of_the_hosts_drive():
            assert first <= identity < highest

    def test_the_hosts_console_has_a_number_of_its_own_among_them(self):
        # The UART's line is a source of the APLIC, and the module has the
        # APLIC send the identity of the source's own number. So that
        # number has to be an identity, and not one of the drive's.
        first = the_first_number_that_is_an_identity()

        assert first <= UART_SOURCE <= Aplic.SOURCES

    def test_no_identity_of_the_hosts_drive_is_a_number_of_an_aplic_source(
        self,
    ):
        # The numbers up to an APLIC's last source are kept for devices
        # with a wire, on whichever die's APLIC. The module takes a number
        # for a source when a device has it at one, and would then set a
        # source up for the drive's vector, which is no line at all.
        assert min(the_identities_of_the_hosts_drive()) > Aplic.SOURCES

    def test_every_source_of_the_aplic_has_an_identity_of_its_own_number(self):
        assert host().imsic.component.identities > Aplic.SOURCES


def the_first_number_that_is_an_identity():
    """Where the module's `irq_enable` starts taking a number for an identity."""
    glue = ZEPHYR_MODULE / "drivers/interrupt_controller/imsic_irq.c"
    said = re.search(
        r"^#define FIRST_IDENTITY (\d+)$", glue.read_text(), re.MULTILINE
    )
    assert said is not None, f"{glue} does not say where identities start"
    return int(said.group(1))


def bindings():
    """The module's bindings, by the compatible each says it is for."""
    found = {}
    for binding in (ZEPHYR_MODULE / "dts/bindings").rglob("*.yaml"):
        said = re.search(
            r"^compatible: \"(.+)\"$", binding.read_text(), re.MULTILINE
        )
        assert said is not None, f"{binding} names no compatible"
        found[said.group(1)] = binding
    return found


def our_compatibles_in_the_devicetrees():
    """Every compatible of socpuppet's own that a devicetree in the module has.

    The boards' devicetrees and the shields' overlays are what firmware is
    built against, and each is generated from a board's description.
    """
    found = set()
    for pattern in ("*.dts", "*.dtsi", "*.overlay"):
        for devicetree in ZEPHYR_MODULE.rglob(pattern):
            found.update(
                re.findall(
                    r'compatible = "(socpuppet,[^"]+)"', devicetree.read_text()
                )
            )
    assert found, "no devicetree in the module has a compatible of ours"
    return found


def compatibles_the_drivers_are_for():
    """What each of the module's drivers says it is the driver for."""
    found = {
        compatible
        for source in (ZEPHYR_MODULE / "drivers").rglob("*.c")
        for compatible in re.findall(
            r"^#define DT_DRV_COMPAT (\w+)$", source.read_text(), re.MULTILINE
        )
    }
    assert found, "no driver in the module says what it is for"
    return found


def vendors_zephyr_is_told_of():
    """The vendors the module gives Zephyr a prefix for."""
    prefixes = ZEPHYR_MODULE / "dts/bindings/vendor-prefixes.txt"
    return {
        line.split()[0]
        for line in prefixes.read_text().splitlines()
        if line and not line.startswith("#")
    }


def the_number_a_cpu_knows_its_plic_by():
    """Which of its CPU's interrupts a board's PLIC drives.

    It is one number for every board with a CPU, and the SSD's is asked.
    """
    (entry,) = (
        entry
        for entry in ssd(host=idle_host).platform.interrupt_map()
        if entry.line.endswith("plic.irq")
    )
    return entry.number
