# SPI flash

`sp.SpiFlash(size=...)` · C++ `socpuppet::SpiFlash` · registry name `spi_flash`

## What it stands for

The chip a system keeps its firmware in, and the controller it is reached through. 🎓 A boot ROM cannot be changed once the chip is made, so the firmware it starts is kept somewhere that can: a flash memory, a chip of a few megabytes on an SPI bus. SPI is a serial bus of four wires, and a controller on the SoC speaks it.

A flash is read in two ways, and a real controller offers both:

- **By commands.** A driver writes a command byte and an address to the controller's registers and reads the data back a byte at a time. That is how an operating system reads it, and the only way to erase or write it.
- **Like memory.** The controller maps the flash into the address space and does the commands itself. This is called execute in place (XIP), because code can even run straight from it. It is how a boot ROM reads its image: a ROM has no room for an SPI driver.

## What it does

```python
flash = io.add("boot_flash", sp.SpiFlash(size=16 * 1024 * 1024))
bus.map(flash.xip, base=0x1020_0000)       # the flash, read like memory
bus.map(flash.socket, base=0x100D_0000)    # the controller's registers
platform.build()
platform.load_binary("image.img", at=0x1020_0000)
```

| | |
|---|---|
| **The window** (`xip`) | The flash, read like memory, `size` bytes of it. |
| **The controller** (`socket`) | The SPI controller's registers, a page. |

- **Reads through the window** are answered from the flash. An erased flash reads as 0xFF, every bit a one, as NOR flash does.
- **A write through the window is refused**, with a command-error response, and changes nothing. In a script that is a `sp.BusError`.
- **A read past the end** is an address error.
- **No DMI**, the direct memory interface that lets a CPU read a memory's bytes through a pointer. Every read through the window is a transaction, so a trace shows a boot ROM fetching its image, and across a die-to-die link each read crosses it.
- **Loading.** 🧵 `platform.load_binary(file, at=...)` and `platform.poke(...)` fill the flash through the window, by debug transport, as they fill a RAM. Unlike a [ROM](rom.md) it can be filled at any time: a flash is the part that can be changed.

## What it leaves out

- 🚧 **A devicetree node.** Firmware is not told of the flash yet: its boot ROM learns where its image is from the [system controller](system-controller.md). The controller's registers answer, and the chip behind them reads, programs and erases; telling a driver so is M18's next step.
- **Wear.** A real flash wears out after so many erases, and this one never does. A debugger's write through the window puts any bytes anywhere, as a factory's programmer would.
- **Timing.** A read through the window takes no time of its own.
- **The controller's say over the window.** A real controller's window works once firmware has enabled it and told it which read command the chip wants. This one answers whatever those registers hold.
- **More than 16 MiB**, the most three address bytes reach.

## Under the hood

💡 Half of this one is borrowed. The SPI controller is SiFive's, from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals) by Minres, behind the adapter `src/socpuppet/models/spi_controller.cpp`, which is the bus's wires: it hands each byte to the chip whose chip select is low. The chip is socpuppet's own, `src/socpuppet/core/spi_nor_chip.cpp`, a NOR flash of Winbond's W25Q kind written against QEMU's `m25p80` as the reference. The window is ours too: it reads the chip's bytes straight, as a controller's memory-mapped mode does.

🦜 Until M18 both halves were borrowed, Minres's QSPI controller and VPV's flash chip, and the chip knew no read command ([history/decisions.md](../history/decisions.md), 2026-10-27).

`tests/cpp/platform/spi_flash_test.cpp` holds the flash, `tests/cpp/contracts/spi_controller_contract.h` the controller, and `tests/cpp/unit/spi_nor_chip_test.cpp` the chip.
