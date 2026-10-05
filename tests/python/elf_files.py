"""Small ELF images for the tests to load, so that they need no toolchain."""

import struct

RISCV = 243  # the ELF machine number for RISC-V
EXECUTABLE = 2
LOADABLE = 1
READ_AND_EXECUTE = 5  # a segment's permission flags
ALIGNMENT = 4


def elf_image(*, xlen, entry, segments):
    """The bytes of an ELF file for a RISC-V program.

    `segments` is a list of (physical address, bytes). The file is a header,
    then one program header per segment, then the segments' bytes.
    """
    wide = xlen == 64
    header_size, program_header_size = (64, 56) if wide else (52, 32)
    data_at = header_size + program_header_size * len(segments)
    ident = b"\x7fELF" + bytes([2 if wide else 1, 1, 1]) + bytes(9)
    header = struct.pack(
        "<16sHHIQQQIHHHHHH" if wide else "<16sHHIIIIIHHHHHH",
        ident,
        EXECUTABLE,
        RISCV,
        1,  # version
        entry,
        header_size,  # where the program headers start
        0,  # no section headers
        0,  # flags
        header_size,
        program_header_size,
        len(segments),
        0,
        0,
        0,
    )
    program_headers = b""
    body = b""
    for address, data in segments:
        offset = data_at + len(body)
        size = len(data)
        if wide:
            program_headers += struct.pack(
                "<IIQQQQQQ",
                LOADABLE,
                READ_AND_EXECUTE,
                offset,
                address,
                address,
                size,
                size,
                ALIGNMENT,
            )
        else:
            program_headers += struct.pack(
                "<IIIIIIII",
                LOADABLE,
                offset,
                address,
                address,
                size,
                size,
                READ_AND_EXECUTE,
                ALIGNMENT,
            )
        body += data
    return header + program_headers + body


def elf_file(directory, *, xlen, entry, segments):
    """Write such an image into `directory` and return the file's path."""
    path = directory / "program.elf"
    path.write_bytes(elf_image(xlen=xlen, entry=entry, segments=segments))
    return path
