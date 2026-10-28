"""🐧 Linux on the host the quick way, as the package boots it."""

import functools

import pytest

import link_trace
import linux_shell
import socpuppet as sp
from cast import (
    FW_JUMP_BIN,
    INITRAMFS_CPIO,
    LINUX_BIN,
    MANAGER,
    ROOTFS_EXT4,
    SSD,
)
from socpuppet import ftl, gpt, linux
from socpuppet.boards.host import UART_OFFSET
from socpuppet.boards.manager import add_manager, scripted_manager
from socpuppet.boards.ssd import add_ssd, scripted_firmware

IMAGES = (FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4)
#: With its root on the drive, Linux boots with the initramfs, on a host
#: whose IO manager and SSD run their own firmware: by the part of
#: `firmware/build.py` that builds each.
ON_THE_DRIVE = {
    FW_JUMP_BIN: "opensbi linux",
    LINUX_BIN: "opensbi linux",
    ROOTFS_EXT4: "opensbi linux",
    INITRAMFS_CPIO: "opensbi linux",
    MANAGER: "zephyr",
    SSD: "zephyr",
}


class TestWhenAnImageIsMissing:
    @pytest.mark.parametrize("missing", IMAGES)
    def test_it_is_refused_with_its_path_and_the_command_that_builds_it(
        self, tmp_path, missing
    ):
        for image in set(IMAGES) - {missing}:
            (tmp_path / image).write_bytes(b"spam")

        with pytest.raises(FileNotFoundError) as refused:
            linux.host_with_linux(tmp_path)

        assert str(tmp_path / missing) in str(refused.value)
        assert "uv run firmware/build.py opensbi linux" in str(refused.value)


class TestWhenAnImageForTheRootOnTheDriveIsMissing:
    @pytest.mark.parametrize("missing", ON_THE_DRIVE)
    def test_it_is_refused_with_its_path_and_the_command_that_builds_it(
        self, tmp_path, missing
    ):
        for image in set(ON_THE_DRIVE) - {missing}:
            (tmp_path / image).write_bytes(b"spam")

        with pytest.raises(FileNotFoundError) as refused:
            linux.host_with_linux(tmp_path, root="drive")

        assert str(tmp_path / missing) in str(refused.value)
        assert f"uv run firmware/build.py {ON_THE_DRIVE[missing]}" in str(
            refused.value
        )


class TestWhenAnImageForTheRootOnTheDriveIsMissingAndDtcIsNotInstalled:
    @pytest.mark.parametrize("missing", ON_THE_DRIVE)
    @pytest.mark.usefixtures("dtc_is_not_installed")
    def test_it_is_the_image_that_is_refused(self, tmp_path, missing):
        for image in set(ON_THE_DRIVE) - {missing}:
            (tmp_path / image).write_bytes(b"spam")

        with pytest.raises(FileNotFoundError) as refused:
            linux.host_with_linux(tmp_path, root="drive")

        assert str(tmp_path / missing) in str(refused.value)


class TestWhenAnIommuIsAskedForWithTheRootOnVirtio:
    def test_it_is_refused_for_want_of_a_drive_to_put_behind_it(self, tmp_path):
        with pytest.raises(ValueError, match='root="drive"'):
            linux.host_with_linux(tmp_path, root="virtio", iommu=True)


@pytest.fixture
def a_host_with_its_root_on_the_drive(firmware):
    """The host `root="drive"` builds, from the images the build left.

    A missing image skips the test, with the command that builds it.
    """
    for image in ON_THE_DRIVE:
        firmware(image)
    return linux.host_with_linux(firmware(ROOTFS_EXT4).parent, root="drive")


@pytest.mark.platform
class TestWhenTheRootIsOnTheDrive:
    def test_the_ssds_nand_holds_the_root_filesystem_in_partition_1(
        self, a_host_with_its_root_on_the_drive, firmware
    ):
        rootfs = firmware(ROOTFS_EXT4).read_bytes()
        nand = a_host_with_its_root_on_the_drive.drive.ssd.nand

        drive = ftl.drive_image(nand.contents, nand.component)

        first, *_ = gpt.partitions(drive)
        assert first.kind == gpt.LINUX_FILESYSTEM
        assert first.data[: len(rootfs)] == rootfs

    def test_the_host_has_the_io_manager(
        self, a_host_with_its_root_on_the_drive
    ):
        assert a_host_with_its_root_on_the_drive.manager is not None


@pytest.mark.platform
class TestWhenTheSsdHasAScriptForItsFirmware:
    def test_it_has_no_cpu_and_needs_no_image(self, firmware, tmp_path):
        images = images_but(firmware, SSD, tmp_path)
        a_scripted_ssd = functools.partial(
            add_ssd, firmware=scripted_firmware().script
        )

        board = linux.host_with_linux(
            images, root="drive", drive=a_scripted_ssd
        )

        assert board.drive.ssd.cpu_kit is None


@pytest.mark.platform
class TestWhenTheManagerIsAScript:
    def test_it_has_no_cpu_and_needs_no_image(self, firmware, tmp_path):
        images = images_but(firmware, MANAGER, tmp_path)
        a_scripted_manager = functools.partial(
            add_manager, script=scripted_manager().script
        )

        board = linux.host_with_linux(
            images, root="drive", manager=a_scripted_manager
        )

        assert board.manager.cpu_kit is None


def images_but(firmware, left_out, directory):
    """`directory` with every image for the root on the drive but `left_out`.

    Links to the images the build left, so nothing is copied.
    """
    for image in set(ON_THE_DRIVE) - {left_out}:
        (directory / image).symlink_to(firmware(image))
    return directory


#: How long OpenSBI may take to say its first word on the UART, which is
#: on the other die: it says it at about 300 ms of the CPU's time.
SPEAKS_WITHIN = sp.ms(2000)


@pytest.fixture
def linux_images(firmware):
    """The directory of every image Linux on the virtio disk needs.

    A missing image skips the test.
    """
    return linux_shell.linux_images(firmware)


@pytest.mark.platform
class TestWhenTheLinkIsTraced:
    def test_what_crosses_the_link_is_recorded(self, linux_images):
        board = linux.host_with_linux(linux_images, trace=True)

        run_until_opensbi_speaks(board)

        # ⚠️ An address in the trace is the IO die's own, where the UART is.
        assert any(
            each.command == "write" and each.address == UART_OFFSET
            for each in link_trace.sent_to_the_io_die(board)
        )


@pytest.mark.platform
class TestWhenTheLinkIsNotTraced:
    def test_nothing_is_recorded(self, linux_images):
        board = linux.host_with_linux(linux_images)

        run_until_opensbi_speaks(board)

        assert not board.platform.trace


def run_until_opensbi_speaks(board):
    """Run until OpenSBI's first word has crossed the link to the UART."""
    spoke = board.platform.run_until(
        lambda: bool(board.uart.output), timeout=SPEAKS_WITHIN
    )
    assert spoke, "OpenSBI said nothing on the UART"


class AConsole:
    """🎭 A console for a shell that answers from a script."""

    def __init__(self):
        self.output = ""
        self.typed = ""

    def write(self, text):
        self.typed += text


class APlatform:
    """🎭 A platform whose run prints `prints` on `console`, then asks."""

    def __init__(self, console, prints):
        self.console = console
        self.prints = prints

    def run_until(self, condition, timeout=None):
        self.console.output += self.prints
        return bool(condition())


class ABoard:
    """🎭 A host with Linux at its virtio console, as `linux.ask` sees it."""

    class Virtio:
        pass

    def __init__(self, prints):
        self.virtio = ABoard.Virtio()
        self.virtio.console = AConsole()
        self.platform = APlatform(self.virtio.console, prints)


class TestWhenAskedAtThePrompt:
    def test_the_answer_is_what_the_shell_said_between_echo_and_prompt(self):
        board = ABoard(prints="uname -a\r\nLinux spam\r\nsocpuppet:~# ")

        answer = linux.ask(board, "uname -a")

        assert answer == "Linux spam\r\n"
        assert board.virtio.console.typed == "uname -a\n"

    def test_the_terminals_escape_sequences_are_left_out(self):
        board = ABoard(
            prints="ls\r\n\x1b[1;36mspam\x1b[m\r\nsocpuppet:~# \x1b[6n"
        )

        answer = linux.ask(board, "ls")

        assert answer == "spam\r\n"


class TestWhenTheShellDoesNotPromptAgain:
    def test_it_is_a_timeout_that_names_the_command(self):
        board = ABoard(prints="spam\r\n")

        with pytest.raises(TimeoutError, match="spam"):
            linux.ask(board, "spam")
