"""🧦 `socpuppet run`: an image run on a board, its console printed."""

import pathlib
import subprocess

import pytest

import ssd_zephyr_firmware
from cast import (
    DISK_TEST,
    GREETING,
    HELLO_WORLD,
    ROM_FOR_A_32_BIT_CPU,
    ROM_FOR_A_64_BIT_CPU,
    SYNCHRONIZATION,
)
from elf_files import elf_file
from processes import run_socpuppet, start_socpuppet
from riscv_program import SPIN, a_program_that_says
from socpuppet import _core, ztest
from socpuppet.boards import host
from zephyr_module import BOARDS

#: Simulated milliseconds, and far more than a boot ROM needs to load
#: Zephyr's `hello_world` and the sample to speak, which takes under ten.
#: The sample gives no verdict, so a run of it goes on until it is stopped.
LONG_ENOUGH_TO_SAY_HELLO = "100"


def a_program(directory, *, xlen=64):
    """An ELF file called `program.elf` that nothing will run."""
    return elf_file(
        directory,
        xlen=xlen,
        entry=host.RAM_BASE,
        segments=[(host.RAM_BASE, b"Spam, spam, spam")],
    )


def boot_from_rom(firmware, rom, *arguments):
    """Run the command where it finds the boot ROM that `firmware` found.

    The ROM is one of the images `firmware/build.py` builds, so a test
    without them is skipped.
    """
    return run_socpuppet(
        "run", *arguments, SOCPUPPET_FIRMWARE_DIR=str(firmware(rom).parent)
    )


class TestWhenTheRunCommandIsGivenABoardThereIsNot:
    def test_it_fails_in_one_line_that_names_it_and_the_boards_there_are(
        self, tmp_path
    ):
        result = run_socpuppet(
            "run", str(a_program(tmp_path)), "--board", "spam", check=False
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "spam" in line
        for board in BOARDS:
            assert board in line


class TestWhenTheRunCommandIsGivenAShieldForABoardThatTakesNone:
    def test_it_fails_in_one_line_that_says_the_board_takes_none(
        self, tmp_path
    ):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path, xlen=32)),
            "--board",
            "socpuppet_iomgr",
            "--shield",
            "socpuppet_host_drive",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "socpuppet_iomgr takes no shield" in line


class TestWhenTheRunCommandIsGivenAShieldTheSsdDoesNotTake:
    def test_it_fails_in_one_line_that_names_the_one_the_ssd_takes(
        self, tmp_path
    ):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path, xlen=32)),
            "--board",
            "socpuppet_ssd",
            "--shield",
            "socpuppet_host_drive",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "socpuppet_ssd_host" in line


#: Simulated milliseconds. The shield's host waits a second for the drive
#: to say it is ready, which is as long as socpuppet's frontend says that
#: may take, so a run this long has seen it give up if it was going to.
LONGER_THAN_A_HOST_WAITS_TO_BE_TOLD_READY = "1100"


class TestWhenTheSsdIsRunWithTheShieldThatIsItsHost:
    """🎭 The shield `socpuppet_ssd_host` is a host in front of the SSD
    that says a host's first words to a drive: it finds it on its PCIe
    link, enables it, waits for it to say it is ready, asks for its queues
    and how big it is, and writes one block."""

    def test_an_image_that_never_says_the_drive_is_ready_fails_the_run_in_one_line_that_says_so(
        self, tmp_path
    ):
        deaf_to_the_host = a_program_that_says("Spam\n", tmp_path)

        result = run_socpuppet(
            "run",
            str(deaf_to_the_host),
            "--board",
            "socpuppet_ssd",
            "--shield",
            "socpuppet_ssd_host",
            "--boot",
            "ram",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "socpuppet_ssd_host" in line
        assert "did not become ready" in line

    def test_the_ssds_own_firmware_gives_that_host_nothing_to_complain_of(
        self, firmware
    ):
        result = boot_from_rom(
            firmware,
            ROM_FOR_A_32_BIT_CPU,
            str(firmware(ssd_zephyr_firmware.IMAGE)),
            "--board",
            "socpuppet_ssd",
            "--shield",
            "socpuppet_ssd_host",
            "--until",
            LONGER_THAN_A_HOST_WAITS_TO_BE_TOLD_READY,
        )

        [line] = result.stderr.strip().splitlines()
        assert "--until" in line


class TestWhenTheRunCommandIsGivenAShieldTheHostDoesNotTake:
    def test_it_fails_in_one_line_that_names_it_and_the_one_the_host_takes(
        self, tmp_path
    ):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path)),
            "--board",
            "socpuppet_host",
            "--shield",
            "spam",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "spam" in line
        assert "socpuppet_host_drive" in line


class TestWhenTheRunCommandIsGivenTheIommusShieldWithoutTheDrives:
    def test_it_fails_in_one_line_that_names_the_drives_shield(self, tmp_path):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path)),
            "--board",
            "socpuppet_host",
            "--shield",
            "socpuppet_host_iommu",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "socpuppet_host_drive" in line


class TestWhenTheRunCommandIsGivenAnImageThatIsNotThere:
    def test_it_fails_in_one_line_that_names_the_file(self, tmp_path):
        result = run_socpuppet(
            "run",
            str(tmp_path / "no_such.elf"),
            "--board",
            "socpuppet_host",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "no_such.elf" in line


@pytest.mark.parametrize("boot", ["rom", "ram"])
class TestWhenTheRunCommandIsGivenAnImageForAnotherKindOfCpu:
    def test_a_32_bit_image_is_refused_for_the_host_in_the_boot_roms_words(
        self, tmp_path, boot
    ):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path, xlen=32)),
            "--board",
            "socpuppet_host",
            "--boot",
            boot,
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "program is a 32-bit image, and this is a 64-bit CPU" in line

    def test_a_64_bit_image_is_refused_for_the_ssd_in_the_boot_roms_words(
        self, tmp_path, boot
    ):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path, xlen=64)),
            "--board",
            "socpuppet_ssd",
            "--boot",
            boot,
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "program is a 64-bit image, and this is a 32-bit CPU" in line


class TestWhenTheRunCommandIsToBootFromARomAndThereIsNoRomWhereItLooks:
    def test_it_fails_in_one_line_that_says_where_and_how_to_build_one(
        self, tmp_path
    ):
        nothing_built = tmp_path / "firmware"

        result = run_socpuppet(
            "run",
            str(a_program(tmp_path)),
            "--board",
            "socpuppet_host",
            "--boot",
            "rom",
            check=False,
            SOCPUPPET_FIRMWARE_DIR=str(nothing_built),
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert str(nothing_built / ROM_FOR_A_64_BIT_CPU) in line
        assert "firmware/build.py" in line


class TestWhenTheRunCommandLoadsZephyrsHelloWorldIntoTheHostsRam:
    def test_it_prints_what_the_image_says_on_its_console(self, firmware):
        result = run_socpuppet(
            "run",
            str(firmware(HELLO_WORLD)),
            "--board",
            "socpuppet_host",
            "--boot",
            "ram",
            "--until",
            LONG_ENOUGH_TO_SAY_HELLO,
        )

        assert GREETING in result.stdout


class TestWhenTheRunCommandIsAskedForQboxsCpuOnABoardThatHasNoChoice:
    def test_it_fails_in_one_line_that_says_which_board_has_one(self, tmp_path):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path, xlen=32)),
            "--board",
            "socpuppet_ssd",
            "--cpu",
            "qbox_cpu",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "socpuppet_ssd" in line
        assert "socpuppet_host" in line


class TestWhenSocpuppetCpuNamesACpuThereIsNot:
    def test_the_run_command_fails_in_one_line_that_names_it_and_the_cpus_there_are(
        self, tmp_path
    ):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path)),
            "--board",
            "socpuppet_host",
            check=False,
            SOCPUPPET_CPU="spam",
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "spam" in line
        assert "dbt_rise_cpu" in line
        assert "qbox_cpu" in line


@pytest.mark.skipif(_core.has_qbox, reason="this build has QBox's CPU")
class TestWhenTheRunCommandIsAskedForQboxsCpuInABuildWithoutIt:
    def test_it_fails_in_one_line_that_says_how_to_build_one(self, tmp_path):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path)),
            "--board",
            "socpuppet_host",
            # Not the ROM, which the command looks for before anything.
            "--boot",
            "ram",
            "--cpu",
            "qbox_cpu",
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "tools/build_qbox.py" in line

    def test_socpuppet_cpu_asks_for_it_as_the_option_does(self, tmp_path):
        result = run_socpuppet(
            "run",
            str(a_program(tmp_path)),
            "--board",
            "socpuppet_host",
            # Not the ROM, which the command looks for before anything.
            "--boot",
            "ram",
            check=False,
            SOCPUPPET_CPU="qbox_cpu",
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "tools/build_qbox.py" in line


@pytest.mark.skipif(not _core.has_qbox, reason="this build has no QBox")
class TestWhenTheRunCommandLoadsZephyrsHelloWorldIntoTheHostsRamOnQboxsCpu:
    def test_it_prints_what_the_image_says_on_its_console(self, firmware):
        result = run_socpuppet(
            "run",
            str(firmware(HELLO_WORLD)),
            "--board",
            "socpuppet_host",
            "--cpu",
            "qbox_cpu",
            "--boot",
            "ram",
            "--until",
            LONG_ENOUGH_TO_SAY_HELLO,
        )

        assert GREETING in result.stdout


class TestWhenTheRunCommandBootsZephyrsHelloWorldOnTheHostFromItsRom:
    def test_the_rom_says_what_it_loaded_and_then_the_image_speaks(
        self, firmware
    ):
        result = boot_from_rom(
            firmware,
            ROM_FOR_A_64_BIT_CPU,
            str(firmware(HELLO_WORLD)),
            "--board",
            "socpuppet_host",
            "--until",
            LONG_ENOUGH_TO_SAY_HELLO,
        )

        rom, _, image = result.stdout.partition("\n")
        assert rom.startswith(f"rom: {pathlib.Path(HELLO_WORLD).stem}: ")
        assert GREETING in image


@pytest.mark.parametrize("board", ["socpuppet_ssd", "socpuppet_iomgr"])
class TestWhenTheRunCommandBootsZephyrsHelloWorldOnABoardWithA32BitCpu:
    def test_it_prints_what_the_image_says_on_that_boards_console(
        self, firmware, board
    ):
        result = boot_from_rom(
            firmware,
            ROM_FOR_A_32_BIT_CPU,
            str(firmware(f"hello_world_{board}.elf")),
            "--board",
            board,
            "--until",
            LONG_ENOUGH_TO_SAY_HELLO,
        )

        assert f"Hello World! {board}" in result.stdout


class TestWhenAnImageHasGivenNoVerdictByTheTimeTheRunCommandWasToldToStop:
    def test_it_says_so_in_one_line_apart_from_the_console(self, firmware):
        # Zephyr's `synchronization` sample: two threads that take turns to
        # speak for as long as they are let, and no test framework.
        result = run_socpuppet(
            "run",
            str(firmware(SYNCHRONIZATION)),
            "--board",
            "socpuppet_host",
            "--boot",
            "ram",
            "--until",
            "50",
        )

        [line] = result.stderr.strip().splitlines()
        assert "50 ms" in line


class TestWhenAnImageRunByTheRunCommandSaysItsTestsPassed:
    def test_it_stops_there_with_the_verdict_printed_and_no_more_to_say(
        self, firmware
    ):
        # Zephyr's test of its disk interface, built with the shield that
        # gives the host a drive.
        result = boot_from_rom(
            firmware,
            ROM_FOR_A_64_BIT_CPU,
            str(firmware(DISK_TEST)),
            "--board",
            "socpuppet_host",
            "--shield",
            "socpuppet_host_drive",
        )

        assert ztest.parse(result.stdout).passed
        assert result.stderr == ""


class TestWhenAnImageRunByTheRunCommandSaysATestOfItsFailed:
    def test_the_command_fails_with_no_more_said_than_the_console(
        self, tmp_path
    ):
        said = a_program_that_says("PROJECT EXECUTION FAILED\n", tmp_path)

        result = run_socpuppet(
            "run",
            str(said),
            "--board",
            "socpuppet_ssd",
            "--boot",
            "ram",
            check=False,
        )

        assert result.returncode != 0
        assert result.stdout == "PROJECT EXECUTION FAILED\n"
        assert result.stderr == ""


class TestWhenAnImageRunByTheRunCommandGoesToSleepWithNothingToWakeIt:
    def test_it_stops_there_and_says_the_simulation_has_nothing_left_to_do(
        self, tmp_path
    ):
        result = run_socpuppet(
            "run",
            str(a_program_that_says("Spam\n", tmp_path)),
            "--board",
            "socpuppet_ssd",
            "--boot",
            "ram",
        )

        [line] = result.stderr.strip().splitlines()
        assert "nothing left to do" in line


class TestWhenTheLastThingAnImageRunByTheRunCommandSaysIsNotAWholeLine:
    def test_it_is_printed_all_the_same(self, tmp_path):
        result = run_socpuppet(
            "run",
            str(a_program_that_says("Spam\nand eggs", tmp_path)),
            "--board",
            "socpuppet_ssd",
            "--boot",
            "ram",
        )

        assert result.stdout == "Spam\nand eggs\n"


class TestWhenTheRunCommandIsGivenAFileThatIsNoProgram:
    def test_it_fails_in_one_line_that_names_the_file(self, tmp_path):
        not_elf = tmp_path / "spam.txt"
        not_elf.write_bytes(b"Spam, spam, spam")

        result = run_socpuppet(
            "run", str(not_elf), "--board", "socpuppet_host", check=False
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "spam.txt" in line


class TestWhenAnImageRunByTheRunCommandHasSaidALineAndIsStillRunning:
    def test_the_line_has_been_printed_before_the_command_ends(self, tmp_path):
        # A CPU that spins is at work until the run's 30 s of simulated
        # time are up, which is a good ten of the clock on the wall.
        still_running = a_program_that_says("Spam\n", tmp_path, then=SPIN)
        command = start_socpuppet(
            "run",
            str(still_running),
            "--board",
            "socpuppet_ssd",
            "--boot",
            "ram",
        )

        try:
            assert command.stdout.readline() == "Spam\n"
            # A command that kept the line until its end has ended by now,
            # and takes far less than this second to do it.
            with pytest.raises(subprocess.TimeoutExpired):
                command.wait(timeout=1)
        finally:
            command.kill()
            command.communicate()
