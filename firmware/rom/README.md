# The boot ROM 🧦

What a socpuppet CPU runs first when its board is described with `boot=from_rom`: a start in assembly and two pages of C, with no Zephyr under it. It is built for each kind of CPU, as `rom_rv64.elf` and `rom_rv32.elf`, and is about 1.3 KiB.

🎓 A boot ROM is the program a chip is made with. It cannot be changed, so it does as little as it can: find the next program, check it, and start it. That next program is usually a bigger bootloader, and this kind of ROM is called a zero-stage bootloader for it.

What this one does, in order:

1. **Asks where the image is.** The CPU's [system controller](../../docs/models/system-controller.md) has the address in its `BOOT_ADDRESS` register, which is somewhere in the board's [flash](../../docs/models/spi-flash.md).
2. **Reads the header there.** A [boot image](../../docs/models/boot-image.md) starts with 72 bytes that say what the program is called, which kind of CPU it is for, where it goes in memory, where it starts, and what to hand it.
3. **Copies the program into RAM**, a register's width at a time.
4. **Checks the copy**, by its CRC-32, against the one in the header.
5. **Says what it loaded, and jumps to it**, with the hart's number in `a0` and the argument from the header in `a1`, as every RISC-V stage of a boot starts the next: OpenSBI takes the address of its devicetree there.

## What it says

Every line starts with `rom: `, on the board's console.

| The ROM says | When |
|---|---|
| `rom: hello_world_socpuppet_host: 12104 bytes to 0x80000000, jumping to 0x80000000` | ✅ All is well. This is the last thing it says. |
| `rom: no image at 0x10200000` | ❌ What is at `BOOT_ADDRESS` does not start with the four bytes `SOCP`. The flash is empty, or the image was put somewhere else. |
| `rom: hello_world_socpuppet_ssd is a 32-bit image, and this is a 64-bit CPU` | ❌ The image was built for the other kind of CPU. |
| `rom: hello_world_socpuppet_host: bad CRC: its header says 0x031fc435, and its bytes come to 0x7418f4a3` | ❌ The program's bytes are not the ones the header was made for. |
| `rom: stopped by a trap: mcause 0x7, mepc 0x1370, mtval 0x84000000` | ❌ The CPU trapped, in the ROM or in a program that has no trap handler of its own yet. The three numbers are the registers a RISC-V CPU says of a trap in: why, the address of the instruction it was at, and for a refused access the address of that. `mcause` 7 is a write that nothing took, which is what an image with a load address where the board has no memory comes to. |

After any of the ❌ lines the CPU stops, in `wfi`, and nothing is started.

## Build it

`firmware/build.sh` builds it before anything else, with the Zephyr SDK's compiler:

```sh
firmware/build.sh
```

Where the UART, the system controller and the top of RAM are is in `board_rv64.h` and `board_rv32.h`, one for each kind of socpuppet board, and `tests/python/test_rom_firmware.py` holds each to the boards. The header's layout is generated from `regs/boot_image_header.rdl`, which is also what Python writes an image from.

## What it leaves out

- 💡 **It takes its time over the CRC.** The sum is worked out half a byte at a time, with a table of sixteen numbers, as Zephyr's own `crc32_ieee_update()` does. That is about nineteen instructions a byte: 23 ms of a 10 MHz CPU's time for Zephyr's `hello_world`. A ROM that boots a kernel would use a bigger table, or the hardware.
- **A signature.** A CRC catches a flash that has rotted. It does not catch an image that was changed on purpose.
- **A second place to look.** A real ROM often has a fallback: another copy of the image, or a way to load one over a serial line. This one says what is wrong and stops.
- **A check that the image fits.** The ROM's stack is at the top of RAM, and an image long enough to reach it would overwrite it.
