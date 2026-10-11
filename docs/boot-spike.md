# The boot spike: four questions before a CPU boots from flash

This is the report of a spike for milestone M14 in [plan.md](plan.md), run on 2026-10-11. Its code is in `spikes/boot/`, with a [README](../spikes/boot/README.md) that says how to run each part, and goes when the steps that use what it found have landed.

**The questions.** M14 puts a boot ROM, a flash, a system controller and a watchdog on every CPU, and its plan rested on four things nobody had tried:

1. Can the borrowed flash be filled by a debugger's write through the window it is read through?
2. Does the Zephyr SDK's compiler build a program with no Zephyr in it, for both kinds of CPU, where the firmware is built today?
3. Does Zephyr start when its image is copied into RAM as flat bytes, which is what a ROM does?
4. Does Zephyr build for a host with two APLICs and a SiFive watchdog that interrupts through the second?

**The answers.** Yes to all four, and two of them went further than building: the spike's ROM booted Zephyr on the host with nothing loaded into RAM, and Zephyr's shell answered Python on a host with two APLICs. Seven things turned up on the way that the steps have to know, marked ⚠️ below.

## 1. The flash is filled through its window

`spikes/boot/flash_rig_test.cpp` joins VPV-Peripherals' SPI controller (`minres/qspi`), SCC's `spi::spi_channel` and VPV-Peripherals' flash chip (`generic/spi_mem`), and stands where a bus would.

| What was tried | What happened |
|---|---|
| A debug write of 8 bytes through `xip_sck`, with no process running | All 8 landed in the chip |
| A debug read of the same | The 8 bytes |
| A read with time, from a thread | The 8 bytes, `TLM_OK_RESPONSE` |
| A write with time through the window | ⚠️ Taken, and the bytes changed |
| A read of the controller's `status` register | `0x20` |
| A request for DMI through the window | Not offered |
| A read 256 MB in, just past the chip's fixed size | ⚠️ The process ends: "pointer being freed was not allocated" |

So `platform.load_binary` can fill a flash the way `load_elf` fills a RAM, and the borrowed pair needs no patch for it. What the adapter has to do itself:

- ⚠️ **Refuse a write with time.** The window is a memory to the borrowed model, and a real flash is not written by storing to it.
- ⚠️ **Refuse an access past its own size before the chip sees it.** The chip is 256 MB whatever a platform asks for, and an access past that is not an error response but the end of the process.
- ⚠️ **Take SCC's SPI sockets as headers only.** They are in the directory of SCC's `interfaces` library, which also has AXI and CHI in it. socpuppet has never built that library, and with this compiler its transaction recording does not compile. The adapter's library adds the directory to its include path and links nothing new.
- **Link ELFIO.** The chip's source reads ELF files for its own preload, which socpuppet does not use, and needs the library all the same. It is in the build already, for socpuppet's own loader.

## 2. A ROM builds with the SDK's compiler, and boots a host

`spikes/boot/rom/` is a ROM of 180 bytes: `start.S` sets a stack up at the top of RAM and calls C, and `main.c` checks a magic number, copies the image to its address, says `rom: jumping` on the UART and jumps. `build.sh` there builds it for RV64 and RV32 with `riscv64-zephyr-elf-gcc` from the SDK that `firmware/build.sh` has already fetched, in the devcontainer's image on an Intel Mac.

- **One compiler does both.** `-march=rv64imac_zicsr -mabi=lp64` and `-march=rv32imac_zicsr -mabi=ilp32`, with `-ffreestanding -nostdlib -nostartfiles`. The SDK has the 32-bit libraries too (`rv32imac_zicsr_zifencei/ilp32`), should the ROM ever want `libgcc`.
- ⚠️ **The linker script goes to gcc with `-T`, not to the linker with `-Wl,-T`.** The SDK's gcc is set up for picolibc and uses picolibc's own script unless it sees a `-T` of its own. Given `-Wl,-T,rom.ld` it linked the ROM at `0x1000_0000`, with a stack and a heap nobody asked for, and said nothing.
- **The script asserts that the ROM has no data.** A ROM cannot be written, so `.data` and `.bss` must be empty, and the link fails if they are not.

`spikes/boot/rom_boots.py` then runs it. The host's reset vector is moved to `0x1000`, 🎭 a plain `sp.Memory` there holds the ROM, another stands in for the flash with `hello_world`'s bytes behind a header, and the RAM is checked to be empty:

```text
rom: jumping
*** Booting Zephyr OS build v4.4.2 ***
Hello World! socpuppet_host/socpuppet_rv64
(13.00 ms of simulated time)
```

- ⚠️ **A copy a byte at a time is slow in simulated time.** 11,664 bytes took 12 ms, a microsecond a byte, against a millisecond for the whole boot when Python loads the image. The real ROM copies a word at a time, and step 12 measures both tiers.

## 3. Zephyr starts from a flat copy

`spikes/boot/bin_in_ram.py` writes `hello_world_socpuppet_host.bin` at the start of RAM in one piece, where `load_elf` writes segments, and Zephyr greets. A Zephyr image for these boards runs from where it is loaded and clears its own `.bss`, so a copy is all it needs.

`spikes/boot/flatten.py` asks whether the image tool needs the `.bin` at all. For all eleven images, the ELF's segments laid out from the lowest address are the same length as `objcopy`'s `.bin`, and differ from it in a handful of bytes: the gaps between sections, which are zero in the ELF and `0xFF` in the `.bin`. Nothing reads a gap. So `socpuppet boot-image` wraps an ELF and needs no other file. The nine images for socpuppet's own boards are one segment each, and the two for QEMU's boards are two.

## 4. Zephyr builds, and runs, with two APLICs

`spikes/boot/zephyr/build.sh` builds `hello_world`, the shell sample and Zephyr's watchdog sample for `socpuppet_host` against a copy of socpuppet's module with three things laid over it:

- **A devicetree with what M14 adds**: a second APLIC at `0x0C00_0000`, a `sifive,wdt` at `0x0010_1000` whose interrupt is source 17 of it, and a system controller at `0x0010_0000`.
- **Two bindings.** `socpuppet,aplic` includes Zephyr's `riscv,aplic` and adds `socpuppet,sources`, the sources with a device's line on them. `socpuppet,system-controller` includes `syscon`. A node's first compatible is ours and its second Zephyr's, and Zephyr's drivers still find their nodes: `CONFIG_RISCV_APLIC` and `CONFIG_WDT_SIFIVE` are both on.
- **The glue, taught that there are two.** A table from an interrupt's number to the APLIC that has it, made at build time from each node's `socpuppet,sources`. A number no APLIC lists is an identity for a message from somewhere else, where today every number up to 31 is taken for a source.

All three images built. `spikes/boot/two_aplics.py` then ran the shell image on a host given a second APLIC by hand, and the shell answered `kernel version`: Zephyr's APLIC driver with two instances, and the console's interrupt found on the right one.

- ⚠️ **Not tried: the watchdog image running.** There is no watchdog model yet. Zephyr's driver builds against a node whose interrupt is an APLIC's source, which is all the spike asked.
- ⚠️ **An APLIC with no device on it yet.** `DT_FOREACH_PROP_ELEM` over a property that is not there does not compile, so a node with no sources either has the property empty or the glue asks first. Step 6 has a compute-die APLIC with nothing wired to it until step 7, and meets this at once.

## What changes in the plan

Nothing in the order or the scope. The steps gain what is marked ⚠️ above: step 8's adapter refuses a timed write and an access past its size, and takes SCC's SPI headers without the library. Step 10's `build.sh` passes `-T` to gcc, and its ROM copies words. Step 6 decides how an APLIC with no sources is written.
