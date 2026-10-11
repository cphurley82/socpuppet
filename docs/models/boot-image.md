# Boot image

`socpuppet.boot_image` · `socpuppet boot-image firmware.elf -o firmware.img`

## What it stands for

What a flash holds for a boot ROM to start: a program's bytes with a short header in front that says what to do with them. 🎓 A boot ROM is a few hundred bytes of code that cannot be changed, so it cannot read an ELF file, which is the format a linker writes and takes a library to read. An image is what is left of an ELF once the reading has been done: where the bytes go, where to start, and the bytes.

Real systems each have their own. U-Boot has its `uImage` header, MCUboot its own, a PC's firmware its capsules. This one is socpuppet's, and is as small as will do.

## The header

64 bytes, every number little-endian, with the image's bytes straight after it.

<!-- regs:boot_image_header start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x00` | `MAGIC` | read | What says this is an image at all. 1346588499 `NUMBER`: The four bytes `SOCP`, which as a little-endian number is 0x50434F53. |
| `0x04` | `XLEN` | read | Which kind of CPU the program was built for, by the width of its registers in bits. 32 `RV32`: A program for a 32-bit CPU. 64 `RV64`: A program for a 64-bit CPU. |
| `0x08` | `LOAD_ADDRESS_LOW` | read | Where in memory the program's first byte goes, the low 32 bits. |
| `0x0C` | `LOAD_ADDRESS_HIGH` | read | The high 32 bits, which are zero for a 32-bit CPU. |
| `0x10` | `ENTRY_LOW` | read | Where the CPU starts executing once the program is in memory, the low 32 bits. |
| `0x14` | `ENTRY_HIGH` | read | The high 32 bits. |
| `0x18` | `LENGTH` | read | How many bytes the program is: what follows the header. |
| `0x1C` | `CRC` | read | The CRC-32 of the program's bytes, as zlib and Ethernet compute it. The header is not in it. |
| `0x20` | `NAME[8]` | read | The image's name, as text, for a boot ROM to say which image it could not start. Up to 32 bytes of UTF-8, with zeros after a shorter one. A name of all 32 bytes has no zero after it. |

<!-- regs:boot_image_header end -->

`LOAD_ADDRESS` and `ENTRY` are each two words, so that one header serves a 64-bit CPU and a 32-bit one. The name is there for one reason: a boot ROM that refuses an image can say which.

## Making one

```sh
socpuppet boot-image build/zephyr/zephyr.elf -o zephyr.img
```

```python
from socpuppet import boot_image

image = boot_image.wrap("build/zephyr/zephyr.elf")        # bytes
platform.poke(BOOT_FLASH_BASE, image, via=board.cpu.socket)
```

- **The program's bytes are laid out as they will be in memory**, from the lowest address any segment has, with zeros where the ELF file has a gap. So a boot ROM copies one run of bytes to one address.
- **The name is the file's**, without its extension, cut to 32 bytes, between two characters.
- **The CRC is CRC-32**, the sum zlib, Ethernet and `zlib.crc32` all compute, over the program's bytes and not the header.
- `boot_image.from_elf(path)` is the image before it is bytes, a `BootImage` with the header's fields, and `boot_image.read(bytes)` is the other way: the image those bytes start with, checked as a boot ROM checks it. It raises `ValueError` with a sentence if they are no image, are cut short, or have a CRC that is not their own.

## What it leaves out

- **A signature.** A CRC catches a flash that has rotted or an image cut short. It does not catch one that was changed on purpose: anyone who can write the flash can write a new CRC. A boot that checks who made the image is a secure boot, and the plan leaves it open.
- **A CRC of the header.** The sum is of the program's bytes. A damaged length is nearly always caught, since it changes which bytes are summed. A damaged load address or entry is not caught at all: the boot ROM copies to the wrong place, or jumps to it.
- **More than one segment.** An image is one run of bytes at one address. A program whose segments are far apart becomes one large image, mostly zeros.
- **Anything for the next stage.** A real header says what to pass on: a devicetree's address, a boot argument. This one has no word for it yet.
- **Compression, versions and a second copy** to fall back to, all of which real ones have.

## Under the hood

The header is written once, in `regs/boot_image_header.rdl`, as a register map is. `tools/regs.py` makes of it the table above, `socpuppet/regs/boot_image_header.h` for the boot ROM's C, and `socpuppet.regs.boot_image_header` for Python, so the code that writes a header and the code that reads one cannot disagree about an offset.

💡 A file's header is not a block's registers, and the generator says "register" where this page says "word". The language has what the job needs all the same: named 32-bit words at offsets, and what the numbers in them mean.
