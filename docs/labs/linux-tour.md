# Lab: Linux, end to end 🧪

🐧 Boot a stock Linux kernel on socpuppet's biggest show, type at its shell from your terminal and over `ssh`, then change the cast under it, one piece at a time, and watch what changes: the CPU that runs it, and the 🎭 stand-ins (simplified models that hold a block's place) that give way to the real models. Each step is a command and a few things to look at; the why is a link away. Plan on an hour, most of it waiting for boots on the interpreter.

Every command is run from the top of a checkout. ⚠️ Every boot is its own process: the SystemC kernel cannot be restarted, so one run is one show ([architecture.md](../architecture.md#-one-platform-per-process)). The numbers on this page were measured on an Intel Mac on 2026-10-26; yours will differ, the comparisons will not.

## 1. Before you start

```sh
uv run cmake --preset dev && uv run cmake --build --preset dev   # the simulator
uv run firmware/build.py                                         # every image, the first time: a while
uv run python tools/doctor.py cable qbox                         # what steps 3 and 5 need
```

- The firmware build fetches OpenSBI, Linux and Alpine and builds them; on a Mac the kernel builds in a Docker image ([linux.md](../linux.md#the-kernel-and-its-root)).
- 🩺 The doctor says what this machine lacks for the cable (libslirp, ssh) and for QBox, and how to get it ([setup.md](../setup.md)).

## 2. Boot Linux and type at it

```sh
PYTHONPATH=python uv run python -m socpuppet linux
```

OpenSBI's banner, then the kernel's messages, then a quiet minute, then `socpuppet:~#`. Your keys go to Linux as you press them; **Ctrl-]** leaves, and `poweroff` ends the show. Things to type, and what you are looking at:

| Type | Look at |
|---|---|
| `uname -a` | A stock `6.18` kernel for `riscv64`, built from kernel.org's tree with its own `defconfig` |
| `cat /proc/cpuinfo` | The hart: its ISA string, with `ssaia` for the interrupt architecture, `mmu : sv39` for paging with three levels of page table, and `mvendorid`, the maker's number. Remember that last one for step 5 |
| `cat /proc/interrupts` | The timer comes to the hart directly (`RISC-V INTC`). Every other line is a 🎭 virtio device's wire into the APLIC, which turns it into a message to the IMSIC (`APLIC-MSI`). Type something and watch the console's count go up |
| `ls /sys/bus/virtio/devices` | 🎭 The cast under Linux, `virtio0` to `virtio5`: entropy source, console, disk, network card and the shared directory twice, each under Linux's own driver ([linux.md](../linux.md#the-virtio-cast-under-linux)) |
| `cat /proc/iomem` | What Linux found where: six `virtio_mmio` blocks a page apart from `0x1000_1000`, the UART, the two interrupt controllers. Beside [address-map.md](../address-map.md#the-host): the same addresses, from the same Python description |
| `dmesg \| head -40` | The kernel's first lines again. Where the `earlycon` lines stop is where 🎭 the virtio console took over from the UART |
| `uptime` | Simulated time, which ran ahead of the wall while the CPU worked. Compare with your watch |
| `sleep 3` | Three seconds on your watch too: while the CPU sleeps, the simulated clock keeps to the wall's |

💡 [linux.md](../linux.md#at-its-shell-yourself) has what the terminal does and does not pass on, and why `vi` thinks the screen is 80 by 24.

## 3. ssh in from a second terminal

Leave Linux at its prompt in the first terminal. 🔌 Its network card is plugged into this machine's network, and port 2222 reaches its `ssh`:

```sh
ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@localhost
```

- **No password**: root has none, as at the console. ⚠️ The host key is new at each boot, which is what the two `-o` options are for.
- `scp -P 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null spam.txt root@localhost:/root/` sends a file; `cat /root/spam.txt` at the console in the first terminal reads it back.
- From inside Linux, `ping -c 2 10.0.2.2` reaches the gateway, which is this machine, and `nslookup example.com` resolves through this machine's resolver.
- The key exchange runs on the simulated CPU, so the first connection takes a while. [ethernet-cable.md](../models/ethernet-cable.md) says how a cable with no root works, and what it leaves out.

## 4. Script the boot

Standard output is Linux's console and nothing else, so the show can be piped. This boots, answers, switches off, and tells you how long it took on the wall:

```sh
time (printf 'uname -a\npoweroff\n' | PYTHONPATH=python uv run python -m socpuppet linux --ssh-port 0 > /dev/null)
```

3 minutes here, nearly all of it the CPU working. Write your number down.

## 5. Swap the CPU

The hart is DBT-RISE's interpreter. QBox puts QEMU's CPU in the same slot: the same board around it, devicetree and all, and nothing else changes. QEMU is GPL, so you build it yourself, once:

```sh
uv run tools/build_qbox.py                                 # QBox and its QEMU: minutes
uv run cmake --preset qbox && uv run cmake --build --preset qbox
SOCPUPPET_CPU=qbox_cpu PYTHONPATH=python uv run python examples/linux_hello.py
PYTHONPATH=python uv run python examples/linux_hello.py    # the interpreter again, to compare
```

⚠️ Both presets copy their extension into `python/socpuppet/`, so the one you built last is the one Python imports. To go back, build the `dev` preset again. The example boots as fast as the simulation goes, types `uname -a` and `cat /proc/cpuinfo`, and switches off:

| Look at | DBT-RISE's hart | QBox's hart |
|---|---|---|
| Wall time to the prompt | 173 s | 5 s |
| Simulated time to the prompt | 181 s | 212 s |
| `cat /proc/cpuinfo`, `mvendorid` | `0x669` | `0x0` |
| OpenSBI's banner, `Boot HART ISA Extensions` | `smaia,zicntr,smcsrind,f,d` | the same, with `zihpm` and `sdtrig` |

- 🎓 **Same program, different clocks.** Each hart counts simulated time by instructions, 100 ns each on DBT-RISE and 128 ns on QBox, so the same boot takes a different simulated time, and `uptime` says so. QBox is faster on the wall because QEMU translates the code once and then runs the translation.
- **The same hart, to Linux.** The ISA string and `mmu : sv39` are the same on both: the board's devicetree and OpenSBI describe one hart, and both CPUs play it. What differs is what each lets slip: the vendor number, and two extensions QEMU's hart has that the interpreter does not.
- ⚠️ **`socpuppet linux --cpu qbox_cpu` is not faster on the wall, and `ssh` does not get through to it here.** The terminal keeps the simulated clock to the wall's while the CPU looks asleep, and QBox's hart, which runs ahead of the clock, looks asleep to it while it works: 3 to 4 minutes to the prompt, as on the interpreter, and a key exchange that dropbear gives up on. The example above is how to see QBox's speed, step 3 is the interpreter's, and both are a loose end on [the roadmap](../roadmap.md#loose-ends).
- `SOCPUPPET_CPU=qbox_cpu` in the environment picks QBox's hart for every host a program describes, the examples below included. [qbox-cpu.md](../models/qbox-cpu.md#what-it-does-differently) has the whole list of what the two harts do differently, and why a second hart is kept: two CPUs written by different people rarely share a mistake.

## 6. The whole cast

Linux's root filesystem on the real SSD: three CPUs, three firmwares, the real die-to-die link. The IO die's manager trains the link and lets the host out of reset; the SSD's own Zephyr firmware is the drive, across the link and over PCIe; Linux's own NVMe driver mounts it.

```sh
PYTHONPATH=python uv run python -m socpuppet linux --root drive
```

| Type | Look at |
|---|---|
| `cat /proc/partitions` | `nvme0n1` and `nvme0n1p1`, its one partition, the root; `vda`, 🎭 the virtio disk, blank beside it |
| `dmesg \| grep -i nvme` | Linux finding the drive as PCI function `0000:00:00.0`, making one I/O queue, and mounting `nvme0n1p1` |
| `cat /proc/interrupts` | Two new lines, `PCI-MSIX-0000:00:00.0`: the drive's interrupts are messages, one per queue, into the same IMSIC as the virtio ones |
| `cat /sys/bus/pci/devices/*/class` | `0x010802`: a mass storage controller, non-volatile memory, NVM Express. That is how Linux chose the driver |

- The boot starts quiet: the manager's Zephyr trains the link for 5 ms before the host runs an instruction, and you see none of that on this console. The next step shows it.
- [linux.md](../linux.md#its-root-on-the-drive) has how Python plays the factory that programs the NAND, and [boards.md](../boards.md#the-whole-cast-three-firmwares) the cast with Zephyr on the host.

## 7. Stand-ins against the real thing

The same boot from Python, with the link traced and two of the three CPUs swappable for 🎭 a stand-in, a Python script in the CPU's place with no firmware image and no console:

```sh
PYTHONPATH=python uv run python examples/linux_on_the_drive.py
PYTHONPATH=python uv run python examples/linux_on_the_drive.py --manager script
PYTHONPATH=python uv run python examples/linux_on_the_drive.py --manager script --ssd script
```

Each prints the link's own bring-up packet by packet, then every console as one story with the simulated time of each line, then `cat /proc/partitions` and the NVMe lines of `dmesg`, then how many accesses crossed the link each way. Compare the runs:

| Look at | Real | 🎭 Stand-in |
|---|---|---|
| The manager's lines in the story | `iomgr: training the D2D link`, `D2D link up`, `compute die released` | None: a script has no console. The link's packets on the sideband are the same |
| The write that lets the host go, in the sideband table | 5.1 ms | 5.0 ms: the script takes no time of its own |
| The SSD's lines | `socpuppet SSD firmware: a drive of 8512 pages of 4096 bytes` | None, and `/proc/partitions` is the same: Linux cannot tell |
| The SSD's table of where each block is | On the NAND, saved at shutdown ([ssd-firmware.md](../models/ssd-firmware.md)) | In Python, and gone when the run ends |

- 💡 This is what a stand-in is for: everything around the block you are studying can be simple, and the boot still happens. The pages say what each leaves out: [io-manager.md](../models/io-manager.md#what-it-leaves-out), [ssd-firmware.md](../models/ssd-firmware.md#what-it-leaves-out), and for the link that a manager makes real, [pass-through-link.md](../models/pass-through-link.md#what-it-leaves-out).
- `tests/python/test_ssd_with_its_own_firmware.py` gives the SSD and 🎭 the stand-in drive the same writes and compares what each holds, which is how a stand-in is held to its contract ([architecture.md](../architecture.md#stand-ins-and-contracts)).

## 8. Logs, traces and a debugger

Where to look when you want to see the machinery, or when a boot stops:

- **socpuppet's own lines go to standard error**, Linux's console to standard output; `NO_COLOR=1` turns the colour off. A line like `[W] ssd.bus : target address=0x0 not found for read transaction` is a CPU running an empty memory: an image was not loaded.
- **Two consoles.** `earlycon=sbi` sends the kernel's first words through OpenSBI to the UART, in `board.uart.output` from Python, until 🎭 the virtio console is up. Silence after the early lines usually means the console driver is the problem; `keep_bootcon` on the command line keeps the early one going ([linux.md](../linux.md#when-it-does-not-boot)).
- **What crossed the link** is `platform.trace` on a host built with `trace=True`, as `examples/linux_on_the_drive.py` builds it: every access the host made to its IO die, and every byte of DMA and every interrupt that came back ([tracer.md](../models/tracer.md)). ⚠️ A traced connection refuses DMI and keeps every record, so a traced boot is slower and costs memory.
- **What went down the cable** is a pcap file for Wireshark: `PYTHONPATH=python uv run python examples/linux_cable.py` boots Linux, plugs the cable in, runs this machine's `ssh` down it and leaves `cable.pcap` behind: DHCP, ARP, then the TCP of the session. `tcpdump -nr cable.pcap` reads it too.
- **A debugger on the kernel**, with its symbols:

  ```sh
  PYTHONPATH=python uv run python examples/linux_hello.py --gdb 1234      # the CPU waits
  riscv64-zephyr-elf-gdb build/firmware/linux.elf                          # in a second terminal
  (gdb) target remote :1234
  (gdb) break start_kernel
  (gdb) continue
  (gdb) monitor sysc print_time                                            # the simulated time, on DBT-RISE's hart
  ```

  The kernel's symbols are virtual addresses, and both harts' GDB servers read memory through the CPU's translation, so they work as they are. ⚠️ Leave with `continue`, not `quit`: a stopped CPU stops the whole simulation ([boot-your-firmware.md](../boot-your-firmware.md#debugging-with-gdb), which also says where GDB is on an Intel Mac, whose SDK has none).
- **Every instruction**, on QBox's hart: through the same GDB, `monitor logfile /tmp/trace.log`, `monitor one-insn-per-tb on`, `monitor log exec,nochain`, `continue`; `socpuppet.qemu_trace.pcs` reads the addresses back ([qbox-cpu.md](../models/qbox-cpu.md#what-it-does)). Switch it on near the trouble: a whole boot is billions of lines.

## Where to go next

- [boards.md](../boards.md): the same cast with Zephyr on every CPU, booting from a ROM and a flash, the watchdog, three debuggers at once.
- [architecture.md](../architecture.md): the words (TLM, DMI, the quantum) and the shape of the thing you just drove.
- [roadmap.md](../roadmap.md): which 🎭 stand-in gives way to a real block next.
