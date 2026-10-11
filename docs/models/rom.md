# ROM

`sp.Rom(size=...)` · C++ `socpuppet::Rom` · registry name `rom`

## What it stands for

A read-only memory: the few kilobytes of a chip that are written when it is made and never again. 🎓 A CPU starts executing at a fixed address, its **reset vector**, and on real silicon that address is in a ROM. The program there, a boot ROM, finds the firmware somewhere it can be changed (a flash), copies it into RAM and jumps to it.

## What it does

- **Reads** through its TLM target socket. Addresses are offsets from the start of the ROM, and a router in front of it says where it sits in the address map.
- **Refuses writes.** A write from the bus is answered with a command-error response and changes nothing. In a script that is a `sp.BusError`.
- **Address errors.** A read that runs past the end is answered with an address-error response.
- **DMI, for reading.** It grants direct memory access to the whole ROM, to read through and not to write through, so a CPU fetches its instructions from it at full speed.
- **Loading.** 🧵 `platform.load_elf(...)` and `platform.poke(...)` put the ROM's program there before the first run, by debug transport, as they load a RAM.
- ⚠️ **Loaded once.** The ROM takes a debugger's write until its bus master first comes to it, with a transaction or a request for direct memory access. From then on the chip is made: `poke` and `load_elf` are refused with a `PermissionError` that names the ROM, as a debugger cannot patch a ROM on a board. `peek` always works.

```python
rom = platform.add("rom", sp.Rom(size=60 * 1024))
bus.map(rom.socket, base=0x1000)        # the CPU's reset vector
platform.build()
platform.load_elf("rom.elf")
```

## What it leaves out

- **A devicetree node.** Firmware is not told of the ROM that started it, and QEMU's `virt` machine has no node for its own either. 💡 This matters more than it looks: a devicetree's `zephyr,sram` goes to the lowest memory, and a ROM at a reset vector is below everything.
- **Timing.** A read takes no simulated time.
- **The mask.** A real ROM's contents are fixed by the chip's design. Here they are whatever was loaded, and nothing checks that anything was: a ROM nobody loaded reads as zeros, which a RISC-V CPU takes for an illegal instruction.

## Under the hood

The bytes live in `MemoryStore` (`src/socpuppet/core/memory_store.h`), as a RAM's do. `Rom` is the SystemC wrapper around it, and what it adds is one bit: whether its bus master has come yet. Any transaction sets it, one that is refused as much as one that is answered.

💡 Why not ask the simulator whether the run has started? Because by then it has. `Platform.build()` finishes elaboration, so in SystemC's eyes the simulation is under way before anything is loaded. The ROM goes by its own bus master instead.

Every ROM must pass `RomContract` (`tests/cpp/contracts/rom_contract.h`).
