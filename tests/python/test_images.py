"""🧦 Where a firmware image is: the build directory, or the cache.

A checkout builds its images in its build directory. An installed socpuppet
has none, and keeps its images in the user's cache.
"""

import pathlib

import platformdirs
import pytest

from socpuppet import images, linux, opensbi
from socpuppet.images_release import TAG


@pytest.fixture
def nothing_said(monkeypatch, tmp_path):
    """No directory named, in a working directory with no build/firmware."""
    monkeypatch.delenv("SOCPUPPET_FIRMWARE_DIR", raising=False)
    monkeypatch.delenv("SOCPUPPET_CACHE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def a_checkout(nothing_said):
    """A working directory that is a checkout of socpuppet, with images."""
    (nothing_said / "firmware").mkdir()
    (nothing_said / "firmware/build.py").touch()
    (nothing_said / "build/firmware").mkdir(parents=True)
    return nothing_said


class TestWhichDirectoryImagesAreIn:
    def test_when_the_firmware_directory_is_named_it_is_that_one(
        self, a_checkout, monkeypatch
    ):
        monkeypatch.setenv("SOCPUPPET_FIRMWARE_DIR", "/spam")

        assert images.directory() == pathlib.Path("/spam")

    def test_in_a_checkout_it_is_the_build_directory_there(self, a_checkout):
        assert images.directory() == pathlib.Path("build/firmware")

    def test_away_from_a_checkout_it_is_the_cache_for_this_release(
        self, nothing_said, monkeypatch
    ):
        monkeypatch.setenv("SOCPUPPET_CACHE_DIR", "/eggs")

        assert images.directory() == pathlib.Path("/eggs/images", TAG)

    def test_in_another_project_with_a_build_firmware_it_is_the_cache(
        self, nothing_said, monkeypatch
    ):
        (nothing_said / "build/firmware").mkdir(parents=True)
        monkeypatch.setenv("SOCPUPPET_CACHE_DIR", "/eggs")

        assert images.directory() == pathlib.Path("/eggs/images", TAG)

    def test_with_no_cache_directory_named_it_is_in_the_users_cache(
        self, nothing_said
    ):
        cache = pathlib.Path(platformdirs.user_cache_dir("socpuppet"))

        assert images.directory() == cache / "images" / TAG


class TestFindingAnImage:
    def test_an_image_in_the_directory_is_found_there(self, a_checkout):
        (a_checkout / "build/firmware/spam.elf").write_bytes(b"spam")

        assert images.find("spam.elf").read_bytes() == b"spam"

    def test_a_directory_asked_for_is_the_one_looked_in(
        self, nothing_said, monkeypatch
    ):
        monkeypatch.setenv("SOCPUPPET_FIRMWARE_DIR", "/nowhere")
        (nothing_said / "spam.elf").write_bytes(b"spam")

        assert images.find("spam.elf", nothing_said) == (
            nothing_said / "spam.elf"
        )

    @pytest.mark.parametrize(
        ("name", "part"),
        [
            ("rom_rv64.elf", "rom"),
            ("sbi_payload.elf", "rom"),
            (opensbi.FW_JUMP_BIN, "opensbi linux"),
            ("test_payload.elf", "opensbi"),
            (linux.LINUX_BIN, "opensbi linux"),
            ("linux.elf", "opensbi linux"),
            (linux.ROOTFS_EXT4, "opensbi linux"),
            (linux.INITRAMFS_CPIO, "opensbi linux"),
            ("uefi.fd", "edk2"),
            ("uefi_shell.efi", "edk2"),
            ("hello_world_socpuppet_host.elf", "zephyr"),
            ("hello_world_qemu_riscv64.elf", "zephyr"),
        ],
    )
    def test_a_missing_image_names_itself_and_the_part_that_builds_it(
        self, tmp_path, name, part
    ):
        with pytest.raises(FileNotFoundError) as refused:
            images.find(name, tmp_path)

        assert str(tmp_path / name) in str(refused.value)
        assert f"`uv run firmware/build.py {part}`" in str(refused.value)

    def test_a_missing_image_nothing_is_known_of_says_to_build_everything(
        self, tmp_path
    ):
        with pytest.raises(FileNotFoundError) as refused:
            images.find("spam.elf", tmp_path)

        assert "`uv run firmware/build.py`" in str(refused.value)
