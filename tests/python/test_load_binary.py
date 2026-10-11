"""Loading a file's bytes into a platform at an address.

An ELF file says where each part of it belongs, and `load_elf` reads
that. Other things do not: a flash's contents, a kernel image, a
devicetree blob. Their bytes go where the caller says.
"""

import pytest

import socpuppet as sp

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x100
SPAM = bytes.fromhex("5350414d2c207370616d21")
#: Fewer bytes than SPAM has: where a file that is loaded this far from
#: the end of the RAM runs off it.
ROOM = 8


def master_and_ram():
    """A bus master with a RAM of RAM_SIZE bytes at RAM_BASE, built."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster())
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    platform.build()
    return platform


def a_file_of(directory, data):
    file = directory / "spam.bin"
    file.write_bytes(data)
    return file


@pytest.mark.platform
class TestWhenAFilesBytesAreLoadedAtAnAddress:
    def test_they_land_there_in_order(self, tmp_path):
        platform = master_and_ram()

        platform.load_binary(a_file_of(tmp_path, SPAM), at=RAM_BASE + 0x10)

        assert platform.peek(RAM_BASE + 0x10, len(SPAM)) == SPAM


@pytest.mark.platform
class TestWhenAFilesBytesRunPastTheEndOfTheMemoryTheyAreLoadedInto:
    def test_the_error_names_the_file_its_length_and_the_address(
        self, tmp_path
    ):
        platform = master_and_ram()
        file = a_file_of(tmp_path, SPAM)

        with pytest.raises(LookupError) as error:
            platform.load_binary(file, at=RAM_BASE + RAM_SIZE - ROOM)

        assert str(file) in str(error.value)
        assert f"{len(SPAM)} bytes" in str(error.value)
        assert "0x800000f8" in str(error.value)

    def test_nothing_of_it_is_loaded(self, tmp_path):
        platform = master_and_ram()

        with pytest.raises(LookupError):
            platform.load_binary(
                a_file_of(tmp_path, SPAM), at=RAM_BASE + RAM_SIZE - ROOM
            )

        assert platform.peek(RAM_BASE + RAM_SIZE - ROOM, ROOM) == bytes(ROOM)


@pytest.mark.platform
class TestWhenTheFileToLoadDoesNotExist:
    def test_it_is_refused_in_the_words_load_elf_has_for_it(self, tmp_path):
        platform = master_and_ram()

        with pytest.raises(
            FileNotFoundError, match=r"no_such_spam\.bin.*check the path"
        ):
            platform.load_binary(tmp_path / "no_such_spam.bin", at=RAM_BASE)


@pytest.mark.platform
class TestWhenAPlatformWithTwoBusMastersLoadsAFile:
    def test_the_bytes_land_where_the_named_master_has_that_address_and_nowhere_else(
        self, tmp_path
    ):
        platform, spam, eggs = two_masters_each_with_a_ram()

        platform.load_binary(
            a_file_of(tmp_path, SPAM), at=0x10, via=eggs.socket
        )

        assert platform.peek(0x10, len(SPAM), via=eggs.socket) == SPAM
        assert platform.peek(0x10, len(SPAM), via=spam.socket) == bytes(
            len(SPAM)
        )


def two_masters_each_with_a_ram():
    """Two bus masters, `spam` and `eggs`, each with a RAM of its own at 0."""
    platform = sp.Platform()
    spam = platform.add("spam", sp.ScriptedBusMaster())
    eggs = platform.add("eggs", sp.ScriptedBusMaster())
    spams_ram = platform.add("spams_ram", sp.Memory(size=RAM_SIZE))
    eggs_ram = platform.add("eggs_ram", sp.Memory(size=RAM_SIZE))
    platform.connect(spam.socket, spams_ram.socket)
    platform.connect(eggs.socket, eggs_ram.socket)
    platform.build()
    return platform, spam, eggs
