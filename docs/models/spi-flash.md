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

- **Reads through the window** are answered from the flash. An erased flash reads as zeros here.
- **A write through the window is refused**, with a command-error response, and changes nothing. In a script that is a `sp.BusError`.
- **A read past the end** is an address error.
- **No direct memory access.** Every read through the window is a transaction, so a trace shows a boot ROM fetching its image, and across a die-to-die link each read crosses it.
- **Loading.** 🧵 `platform.load_binary(file, at=...)` and `platform.poke(...)` fill the flash through the window, by debug transport, as they fill a RAM. Unlike a [ROM](rom.md) it can be filled at any time: a flash is the part that can be changed.

## What it leaves out

- 🚧 **A driver's way in.** The controller's registers answer, and the chip behind them knows a handful of SPI commands (identify, write enable, read status) and no read, erase or program. Nothing in socpuppet uses that path yet. The window is all a boot ROM needs, and the rest is M18's.
- **A devicetree node.** Firmware is not told of the flash: its boot ROM learns where its image is from the [system controller](system-controller.md), and nothing else reads it yet.
- **Erase and wear.** A real flash is erased a block at a time to all ones before it can be written, and wears out. Here a debugger's write puts any bytes anywhere.
- **Timing.** A read through the window takes no time of its own.
- **The controller's say over the window.** A real controller's window works once firmware has enabled it and told it which read command the chip wants. This one answers whatever those registers hold.
- **More than 256 MiB**, which is what the borrowed chip holds.

## Under the hood

💡 This one is borrowed, twice over. The SPI controller (`minres/qspi`) and the flash chip (`generic/spi_mem`) are from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals), by Minres, joined by the SPI channel of SCC, and neither is patched. The controller's XIP socket hands an access straight to the chip's memory, a debugger's access too, which is why a platform can fill the flash through the window.

socpuppet wraps the three in an adapter (`src/socpuppet/models/spi_flash.cpp`) whose window is its own:

- **It refuses a write.** The borrowed window takes one, as a memory does.
- **It ends where the flash does.** The borrowed chip is 256 MiB whatever is asked for, and an access past that ends the process where it should be an error ([upstream.md](../upstream.md)).
- **It does not say direct memory access is worth asking for.** The borrowed window says so, and then has no way to grant it.

`tests/cpp/platform/spi_flash_test.cpp` holds it.
