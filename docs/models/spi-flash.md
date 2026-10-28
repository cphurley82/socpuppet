# SPI flash

`sp.SpiFlash(size=...)` · C++ `socpuppet::SpiFlash` · registry name `spi_flash`

## What it stands for

The chip a system keeps its firmware in, and the controller it is reached through. 🎓 A boot ROM cannot be changed once the chip is made, so the firmware it starts is kept somewhere that can: a flash memory, a chip of a few megabytes on an SPI bus. SPI is a serial bus of four wires: a clock, a wire out, a wire back, and a chip select for each device, which the controller pulls low to talk to that one. Every byte out is a byte back, whether the device had anything to say or not.

A flash is read in two ways, and a real controller offers both:

- **By commands.** A driver writes a command byte and an address to the controller's registers and reads the data back a byte at a time. That is how an operating system reads it, and the only way to erase or write it.
- **Like memory.** The controller maps the flash into the address space and does the commands itself. This is called execute in place (XIP), because code can even run straight from it. It is how a boot ROM reads its image: a ROM has no room for an SPI driver.

This one is two real parts. The controller is the SPI controller of SiFive's FE310, which Zephyr's `spi_sifive` and Linux's `spi-sifive` drive. The chip is a NOR flash of Winbond's W25Q kind, which Zephyr's `spi_nor` and Linux's `spi-nor` drive; at 16 MiB it is the W25Q128, the one the host has. Neither operating system needs anything of socpuppet's to use them.

## What it does

```python
flash = io.add("boot_flash", sp.SpiFlash(size=16 * 1024 * 1024))
bus.map(flash.xip, base=0x1020_0000)       # the flash, read like memory
bus.map(flash.socket, base=0x100D_0000)    # the controller's registers
platform.connect(flash.irq, aplic.source29)
platform.build()
platform.load_binary("image.img", at=0x1020_0000)
```

| | |
|---|---|
| **The window** (`xip`) | The flash, read like memory, `size` bytes of it. |
| **The controller** (`socket`) | The SPI controller's registers, a page, 32 bits each. Optional: a CPU that only reads the window needs none. |
| **The interrupt** (`irq`) | High while a watermark firmware enabled is reached. Optional, and Linux's driver needs it connected. |

- **`size`** is a power of two, up to 16 MiB, the most three address bytes reach.
- **Reads through the window** are answered from the flash. An erased flash reads as 0xFF, every bit a one, as NOR flash does.
- **A write through the window is refused**, with a command-error response, and changes nothing. In a script that is a `sp.BusError`.
- **A read past the end** is an address error.
- **No DMI**, the direct memory interface that lets a CPU read a memory's bytes through a pointer. Every read through the window is a transaction, so a trace shows a boot ROM fetching its image, and across a die-to-die link each read crosses it.
- **Loading.** 🧵 `platform.load_binary(file, at=...)` and `platform.poke(...)` fill the flash through the window, by debug transport, as they fill a RAM. Unlike a [ROM](rom.md) it can be filled at any time: a flash is the part that can be changed.
- **The bus's clock** comes from a 50 MHz clock (`sp.SpiFlash.CLOCK_HZ`), divided by the controller's `sckdiv`: the bus runs at the clock over 2 × (`sckdiv` + 1). A byte takes eight of the bus's clocks, so the bytes of a burst are sixteen of the 50 MHz clocks apart at the fastest.

### The chip's commands

A command is the first byte after the chip is selected. A command with an address has three bytes of it next, most significant first. Letting the chip go ends the command, whatever was in flight.

| Command | | |
|---|---|---|
| `0x9F` | Read JEDEC ID | Three bytes: `EF`, Winbond; `40`, the W25Q family; and the capacity, as the power of two of the size (`18` for 16 MiB). |
| `0x05` | Read status | Bit 1 is the write enable latch. It answers again and again for as long as the chip is held. |
| `0x06`, `0x04` | Write enable, write disable | Set and clear the latch. A program or an erase does nothing without it. |
| `0x03` | Read | From the address, a byte at a time, for as long as the chip is held; at the chip's end it goes on from the start. |
| `0x0B` | Fast read | As a read, after one dummy byte. |
| `0x02` | Page program | From the address. Programming only turns ones into zeros: each byte sent is ANDed into the byte held. |
| `0x20`, `0x52`, `0xD8` | Erase 4 KiB, 32 KiB, 64 KiB | The block the address is in, back to 0xFF. |
| `0x60`, `0xC7` | Chip erase | All of it. |

Any other command answers zeros until the chip is let go. 🐧 Linux asks first for the chip's table of parameters (SFDP, `0x5A`), finds none in the zeros, and goes by its own table for the W25Q128.

### Python on the bus

🧵 The chip is at chip select 0, and the controller has three more. A Python object at one of them is a device on the bus: it is told when its chip select goes low (`select()`), answers each byte (`transfer(byte)`, the answer returned), and is told when the select goes high again (`deselect()`). `socpuppet.spi.SpiDevice` is that protocol, and `socpuppet.spi.Loopback` the smallest device, which answers each byte with itself:

```python
from socpuppet.spi import Loopback

flash = sp.SpiFlash(size=16 * 1024 * 1024, devices={1: Loopback()})
```

The host takes them as `host(boot_flash_devices={1: ...})`, and Zephyr's `spi_loopback` test runs with a loopback there (the `socpuppet_host_spi_loopback` shield). 💡 A device is called from the controller's own process, never from the CPU's, so a device of C++ may wait there in simulated time, and a Python one may take its time on the wall's clock.

### The controller's registers

The map is the manual's, as VPV-Peripherals has it. Zephyr's and Linux's drivers each use these:

| Offset | Register | |
|---|---|---|
| `0x00` | `sckdiv` | The bus's clock divider. |
| `0x04` | `sckmode` | The clock's phase and polarity. |
| `0x10` | `csid` | Which chip select is the one in use. |
| `0x14` | `csdef` | Each chip select's level when it is not in use. |
| `0x18` | `csmode` | `0`, auto: selected for each byte; `2`, hold: selected from the first byte until the mode changes; `3`, off: never selected. |
| `0x40` | `fmt` | The frame format. Bit 3, `dir`: the answers to bytes sent are not kept. |
| `0x48` | `txdata` | A write sends a byte, through a FIFO of eight. Reads with bit 31 set while the FIFO is full. |
| `0x4C` | `rxdata` | A read takes the next answer, from a FIFO of eight. Bit 31 is set when there was none. |
| `0x50` | `txmark` | The transmit watermark: reached while fewer bytes than it are waiting to be sent. |
| `0x54` | `rxmark` | The receive watermark: reached while more answers than it are waiting to be read. |
| `0x70` | `ie` | Which watermarks raise `irq`: bit 0 transmit, bit 1 receive. |
| `0x74` | `ip` | Which watermarks are reached, the same bits. |

## What it leaves out

- **Two and four data lines.** The controller keeps `fmt`'s length, protocol and bit order and ignores them: every frame is eight bits, on one data line, most significant bit first. So the chip has no dual or quad reads either, and the devicetree offers neither, so no driver asks for them.
- **The controller's say over the window.** A real controller's window works once firmware has enabled it and told it which read command the chip wants (`fctrl`, `ffmt`). This one reads the chip's bytes whatever those registers hold, and a read through it takes no time of its own.
- **Four chip selects, counted.** `csdef` is 32 bits wide, so Linux counts 32 chip selects where there are four (`cs=32` in its log). Selecting one of the 28 that are not there selects nothing.
- **Time to program and erase.** Each is done at once, so the status register's busy bit is never set. A real W25Q takes about a millisecond to program a page, and tens of seconds to erase the whole chip.
- **The chip's finer points**, where QEMU's `m25p80` does as this one does and neither Linux nor Zephyr can tell: a program carries on past the end of its 256-byte page, where a real W25Q wraps within it; an erase happens as the address's last byte arrives, where a real one waits for the chip to be let go; and the write enable latch stays set after a program or erase, where a real one clears it.
- **The status register's writes, block protection and resets.** The chip has no protected blocks, and answers zeros to the commands that would set them or reset it.
- **Wear.** A real flash wears out after so many erases, and this one never does. A debugger's write through the window puts any bytes anywhere, as a factory's programmer would.
- **More than 16 MiB**, which needs four address bytes.

## In a devicetree

Zephyr's, for a CPU that reaches the controller's registers, has the controller as `sifive,spi0`, with its registers and the window as its two ranges, and the chip inside it at chip select 0, a `jedec,spi-nor` with its JEDEC id and its size, which Zephyr's `spi_nor` reads where it would otherwise ask the chip. A `fixed-clock` node beside it gives the controller's clock, `sp.SpiFlash.CLOCK_HZ`, and socpuppet's `soc.h` gives SiFive's drivers the same number from it. 🐧 Linux's has the same controller, chip and clock without `reg-names`, `jedec-id` and `size`: Linux's `spi-nor` asks the chip for its id and finds its size from it, and `spi-sifive` wants the controller's interrupt, `irq`, connected. Linux then shows the flash as `/dev/mtd0` (`tests/python/test_linux_boot_flash.py`). A CPU that reaches only the window, as a boot ROM's does, is told of no flash: its ROM learns where its image is from the [system controller](system-controller.md).

On the host:

```dts
io_boot_flash: spi@100d0000 {
	compatible = "sifive,spi0";
	reg = <0x0 0x100d0000 0x0 0x1000>, <0x0 0x10200000 0x0 0x1000000>;
	reg-names = "control", "mem";
	clocks = <&io_boot_flash_clock>;
	#address-cells = <1>;
	#size-cells = <0>;
	interrupts-extended = <&io_aplic 29 1 4>;
	io_boot_flash_chip: flash@0 {
		compatible = "jedec,spi-nor";
		reg = <0>;
		jedec-id = [ef 40 18];
		size = <0x8000000>;
		spi-max-frequency = <25000000>;
	};
};
```

## Under the hood

💡 Half of this one is borrowed. The SPI controller is SiFive's, from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals) by Minres, behind the adapter `src/socpuppet/models/spi_controller.cpp`, which is the bus's wires: it hands each byte to the device whose chip select is low, and answers 0xFF, a wire pulled high, where there is none. Five patches put right what Zephyr's and Linux's drivers found in it, from a byte written at time zero that was never sent to a transmit watermark pending the wrong way round; each is in [upstream.md](../upstream.md), with what was read and left alone.

The chip is socpuppet's own, `src/socpuppet/core/spi_nor_chip.cpp`, plain C++ with no simulation kernel, written against QEMU's `hw/block/m25p80.c` as the reference: its tests were written by reading what `m25p80` does, and none of its code was copied, since it is GPL. The window is ours too: it reads the chip's bytes straight, as a controller's memory-mapped mode does.

🦜 Both halves used to be borrowed, Minres's QSPI controller and VPV's flash chip, and the chip knew no read command ([history/decisions.md](../history/decisions.md), 2026-10-27).

`tests/cpp/unit/spi_nor_chip_test.cpp` holds the chip, `tests/cpp/contracts/spi_controller_contract.h` the controller, and `tests/cpp/platform/spi_flash_test.cpp` the two together with the window.
