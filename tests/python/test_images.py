"""🧦 Where a firmware image is: the build directory, or the cache.

A checkout builds its images in its build directory. An installed socpuppet
has none, and keeps its images in the user's cache.
"""

import concurrent.futures
import contextlib
import gzip
import hashlib
import http.server
import io
import pathlib
import threading
import time

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


class AReleaseOfImages:
    """🎭 A stand-in for a release on GitHub: its files, over HTTP."""

    def __init__(self, directory: pathlib.Path) -> None:
        self.directory = directory
        #: What has been asked for, by file name.
        self.asked: list[str] = []
        #: How long each image takes to come, in seconds.
        self.slowness = 0.0

    def holds(self, **images: bytes) -> None:
        """Publish images, gzipped, with their sums, as the release has them."""
        lines = []
        for name, image in images.items():
            name = name.replace("__", ".")
            (self.directory / f"{name}.gz").write_bytes(gzip.compress(image))
            lines.append(f"{hashlib.sha256(image).hexdigest()}  {name}\n")
        (self.directory / "SHA256SUMS").write_text("".join(lines))


class ATerminal(io.StringIO):
    """🎭 A stand-in for a terminal, which keeps what it was told."""

    def isatty(self):
        return True


@pytest.fixture
def release(nothing_said, monkeypatch, tmp_path_factory):
    """A release being served, and no images fetched from it yet."""
    served = AReleaseOfImages(tmp_path_factory.mktemp("release"))

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *arguments, **keywords):
            super().__init__(*arguments, directory=served.directory, **keywords)

        def do_GET(self):
            name = self.path.removeprefix("/")
            served.asked.append(name)
            if name.endswith(".gz"):
                time.sleep(served.slowness)
            super().do_GET()

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # It looks to see if it should stop this often, in seconds, and a test
    # that waited half a second for that would be a slow test.
    threading.Thread(
        target=server.serve_forever, args=(0.01,), daemon=True
    ).start()
    monkeypatch.setenv(
        "SOCPUPPET_IMAGES_URL", f"http://127.0.0.1:{server.server_port}"
    )
    monkeypatch.setenv("SOCPUPPET_CACHE_DIR", str(nothing_said / "cache"))
    yield served
    server.shutdown()
    server.server_close()


def in_the_cache():
    """What is kept in the cache: its images, by name."""
    return {
        path.name
        for path in images.directory().iterdir()
        if not path.name.startswith(".")
    }


class TestFetchingAnImage:
    def test_a_missing_image_is_fetched_and_is_what_was_released(self, release):
        release.holds(spam__elf=b"spam" * 1000)

        found = images.find("spam.elf")

        assert found == images.directory() / "spam.elf"
        assert found.read_bytes() == b"spam" * 1000

    def test_a_second_ask_fetches_nothing(self, release):
        release.holds(spam__elf=b"spam")
        images.find("spam.elf")
        release.asked.clear()

        images.find("spam.elf")

        assert release.asked == []

    def test_only_the_image_asked_for_is_fetched_and_it_is_kept_unpacked(
        self, release
    ):
        release.holds(spam__elf=b"spam", eggs__elf=b"eggs")

        images.find("spam.elf")

        assert in_the_cache() == {"spam.elf"}

    def test_a_directory_asked_for_that_is_the_cache_is_fetched_into(
        self, release
    ):
        release.holds(spam__elf=b"spam")

        found = images.find("spam.elf", images.directory())

        assert found.read_bytes() == b"spam"

    def test_nothing_is_fetched_into_a_directory_that_is_not_the_cache(
        self, release, tmp_path
    ):
        release.holds(spam__elf=b"spam")

        with pytest.raises(FileNotFoundError):
            images.find("spam.elf", tmp_path)

        assert release.asked == []

    def test_nothing_is_fetched_into_the_build_directory_of_a_checkout(
        self, release, nothing_said
    ):
        release.holds(spam__elf=b"spam")
        (nothing_said / "firmware").mkdir()
        (nothing_said / "firmware/build.py").touch()
        (nothing_said / "build/firmware").mkdir(parents=True)

        with pytest.raises(FileNotFoundError) as refused:
            images.find("spam.elf")

        assert release.asked == []
        assert "uv run firmware/build.py" in str(refused.value)

    def test_several_asking_at_once_fetch_it_once_and_all_get_it(self, release):
        release.holds(spam__elf=b"spam")
        release.slowness = 0.2

        with concurrent.futures.ThreadPoolExecutor() as pool:
            found = list(pool.map(lambda _: images.find("spam.elf"), range(4)))

        assert release.asked.count("spam.elf.gz") == 1
        assert {image.read_bytes() for image in found} == {b"spam"}


class TestWhatAFetchSays:
    def test_it_says_one_line_naming_the_image_and_how_big_the_download_is(
        self, release, capsys
    ):
        release.holds(spam__elf=b"spam" * 1_000_000)

        images.find("spam.elf")

        [line] = capsys.readouterr().err.splitlines()
        assert line.startswith("🧦 Fetching spam.elf (")
        assert " MB)" in line

    def test_it_says_nothing_when_nothing_is_fetched(self, release, capsys):
        release.holds(spam__elf=b"spam")
        images.find("spam.elf")
        capsys.readouterr()

        images.find("spam.elf")

        assert capsys.readouterr().err == ""

    def test_it_says_it_in_color_at_a_terminal(self, release, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        release.holds(spam__elf=b"spam")
        terminal = ATerminal()

        with contextlib.redirect_stderr(terminal):
            images.find("spam.elf")

        assert "\x1b[" in terminal.getvalue()

    def test_it_says_it_plainly_at_a_terminal_when_no_color_is_set(
        self, release, monkeypatch
    ):
        monkeypatch.setenv("NO_COLOR", "1")
        release.holds(spam__elf=b"spam")
        terminal = ATerminal()

        with contextlib.redirect_stderr(terminal):
            images.find("spam.elf")

        assert "\x1b[" not in terminal.getvalue()
        assert "spam.elf" in terminal.getvalue()

    def test_it_says_it_plainly_when_it_is_not_at_a_terminal(
        self, release, monkeypatch, capsys
    ):
        monkeypatch.delenv("NO_COLOR", raising=False)
        release.holds(spam__elf=b"spam")

        images.find("spam.elf")

        assert "\x1b[" not in capsys.readouterr().err


class TestWhenAnImageCannotBeFetched:
    """Each says what went wrong, and then how to build the image instead."""

    def test_a_download_that_differs_from_its_sum_is_said_and_not_kept(
        self, release
    ):
        release.holds(spam__elf=b"spam")
        (release.directory / "spam.elf.gz").write_bytes(gzip.compress(b"eggs"))

        with pytest.raises(images.Unavailable) as refused:
            images.find("spam.elf")

        assert "SHA-256" in str(refused.value)
        assert in_the_cache() == set()
        says_how_to_build(refused, "`uv run firmware/build.py`")

    def test_a_download_that_is_not_gzip_is_said_and_not_kept(self, release):
        release.holds(spam__elf=b"spam")
        (release.directory / "spam.elf.gz").write_bytes(b"not gzip at all")

        with pytest.raises(images.Unavailable) as refused:
            images.find("spam.elf")

        assert "gzip" in str(refused.value)
        assert in_the_cache() == set()

    def test_a_download_that_stopped_short_is_said_and_not_kept(self, release):
        release.holds(spam__elf=b"spam" * 1000)
        whole = (release.directory / "spam.elf.gz").read_bytes()
        (release.directory / "spam.elf.gz").write_bytes(
            whole[: len(whole) // 2]
        )

        with pytest.raises(images.Unavailable):
            images.find("spam.elf")

        assert in_the_cache() == set()

    def test_a_name_the_release_has_not_got_is_said_with_the_release(
        self, release
    ):
        release.holds(eggs__elf=b"eggs")

        with pytest.raises(images.Unavailable) as refused:
            images.find("linux.bin")

        assert TAG in str(refused.value)
        assert "linux.bin" in str(refused.value)
        says_how_to_build(refused, "`uv run firmware/build.py opensbi linux`")

    def test_a_release_that_was_never_published_is_said(self, release):
        with pytest.raises(images.Unavailable) as refused:
            images.find("rom_rv64.elf")

        assert "never published" in str(refused.value)
        says_how_to_build(refused, "`uv run firmware/build.py rom`")

    def test_a_file_the_release_lists_but_has_not_got_is_said(self, release):
        release.holds(spam__elf=b"spam")
        (release.directory / "spam.elf.gz").unlink()

        with pytest.raises(images.Unavailable) as refused:
            images.find("spam.elf")

        assert "404" in str(refused.value)
        assert in_the_cache() == set()

    def test_an_unreachable_server_says_to_check_the_connection_or_mirror_it(
        self, release, monkeypatch
    ):
        # 💡 Nothing listens on port 1, here or on any machine that runs this.
        monkeypatch.setenv("SOCPUPPET_IMAGES_URL", "http://127.0.0.1:1")

        with pytest.raises(images.Unavailable) as refused:
            images.find("uefi.fd")

        assert "connection" in str(refused.value)
        assert "SOCPUPPET_IMAGES_URL" in str(refused.value)
        says_how_to_build(refused, "`uv run firmware/build.py edk2`")

    def test_a_cache_that_cannot_be_written_says_how_to_move_it(
        self, release, monkeypatch, nothing_said
    ):
        release.holds(spam__elf=b"spam")
        (nothing_said / "a_file").touch()
        monkeypatch.setenv("SOCPUPPET_CACHE_DIR", str(nothing_said / "a_file"))

        with pytest.raises(images.Unavailable) as refused:
            images.find("spam.elf")

        assert "SOCPUPPET_CACHE_DIR" in str(refused.value)

    def test_it_is_said_in_one_line(self, release):
        release.holds(eggs__elf=b"eggs")

        with pytest.raises(images.Unavailable) as refused:
            images.find("spam.elf")

        assert "\n" not in str(refused.value)

    def test_it_is_a_file_that_is_not_found_to_whoever_asked(self, release):
        with pytest.raises(FileNotFoundError):
            images.find("spam.elf")


def says_how_to_build(refused, command):
    """What to do instead is the last thing an Unavailable says."""
    said = str(refused.value)
    assert command in said
    assert "SOCPUPPET_FIRMWARE_DIR" in said
    assert "docs/boot-your-firmware.md" in said
    assert "github.com/" in said
    assert said.index(command) > said.index(".")
