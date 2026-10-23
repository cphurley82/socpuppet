# PCIe host (this machine's, through pciem)

`sp.PciemHost(vendor_id=..., device_id=..., class_code=..., function_size=..., vectors=...)` · C++ `socpuppet::PciemHost` · registry name `pciem_host` · only in a build with pciem, on Linux

## What it stands for

🐧 This machine's own Linux, as the host of a PCIe function: its root complex, its PCI core and its driver, with nothing played. Where the [PCIe endpoint](pcie-endpoint.md), its link and the puppet's [root complex](pcie-root-complex.md) would stand between a function and a simulated host, this component hands the function to the machine the simulation runs on, and Linux finds it on its own bus as it would a card in a slot. For the SSD, Linux's own `nvme` driver binds it, `lsblk` lists it, and `mkfs.ext4` and `mount` use it.

🎓 To its host, a PCIe device is three things: registers at an address, DMA into the host's memory, and interrupts. [pciem](https://github.com/cakehonolulu/pciem) is a Linux kernel module that lets a program be those three things on the host's own bus, with no virtual machine between. Its kernel side plays the device's configuration space and its BARs, and hands the program the rest: the BAR as shared memory, a ring of the host's writes to it, an ioctl for DMA and one for interrupts. This component is the program's side, and the function's three ports, `bar0`, `dma` and `irq`, are the whole interface.

```text
 this machine's Linux ══ pciem ══ PciemHost ── bar0 ──▶ the function's registers
                                            ◀── dma ─── its DMA
                                            ◀── irq ─── its interrupt lines
```

## Getting it

pciem is GPL-2.0-only, so it is never in socpuppet's wheel, and it is Linux's alone. Whoever wants it builds it, and loads its module, which needs root and a reboot the first time:

```sh
uv run tools/build_pciem.py      # pciem's module, at its pin, into build/pciem
uv run cmake --preset pciem      # socpuppet with it, in build/pciem-dev
uv run cmake --build --preset pciem
uv run python tools/doctor.py pciem
```

[setup.md](../setup.md#6-pciem-optional) has the whole recipe: the kernel's headers, the memory set aside at boot, `insmod`, and root for the host's commands. A build without pciem still knows the name `pciem_host`, and refuses it with how to build one.

## What it does

```python
from socpuppet.boards.real_host import this_machine
from socpuppet.boards.ssd import ssd
from socpuppet.pump import pump

board = ssd(host=this_machine, blocks=131072)   # 64 MiB
board.platform.build()
board.platform.load_elf(ssd_elf, via=board.ssd.cpu.socket)
board.host.start()                               # on the bus: Linux binds it at once
pump(board.platform, far_ends=[board.host], until=lambda: done)
```

Or, from a shell, `socpuppet drive`, which does that until Ctrl-C (below). `ssd(host=this_machine)` puts the component where the scripted host and the endpoint go, so the SSD is described once; `socpuppet.boards.real_host.behavioral_drive(blocks=)` is 🎭 the [behavioral drive](behavioral-nvme.md) in front of it, with no CPU, for when the drive's firmware is not the point.

- **The host's writes, in order, a moment later.** pciem posts each write the host makes to BAR0 in its ring, with its offset, size and data. The pump takes them between runs (`service()`), and a thread of the component's own makes them on `bar0` in the order they came, a delta cycle later, since a transaction needs a process to be made from. A write the function refuses is counted, and the host never hears of it, as on a real bus.
- **The host's reads never reach the function.** The host reads pciem's copy of BAR0, which holds what it last wrote. So at each look of the pump (`refresh()`) the component copies in the registers the function says for itself, CAP, VS and CSTS, as they are now, with debug reads that take no time; `start()` does it once before the drive goes on the bus, so that what the driver reads first is there. ⚠️ A register that changes on its own other than those three, a read that clears what it reads, or a function that is not NVMe, is not served by that.
- **BAR0 starts at zero.** pciem gives a BAR the memory it finds, which may be an earlier device's registers, and Linux reads registers nobody wrote, so the component clears its copy before the device starts ([upstream.md](../upstream.md#a-bars-memory-is-not-cleared-before-the-host-reads-it)).
- **DMA, whole.** An access the function makes on `dma` becomes one copy to or from this machine's memory, at the address the driver gave, through pciem. One that pciem refuses is a `TLM_GENERIC_ERROR_RESPONSE`.
- **A vector on each rising line.** A line of `irq` that rises sends the host that vector. 🎓 The lines are levels and the host is sent edges, so a completion queue's head doorbell, after which NVMe asks for a new message if completions are still waiting, sends again each vector whose line is still high.
- **The puppet's own IDs.** The drive says `0x5350:0xC0DE`, as it does behind the endpoint, and is found by where it is, under pciem's bus, never by name: on a machine with NVMe drives of its own, the puppet's is not `nvme0n1`. `socpuppet.boards.real_host.puppet_function()` is its PCI address.
- 🧵 **A far end, pumped.** The component is outside the simulation as much as in it, as a keyboard is. `board.host` has the descriptor pciem says on (`fileno()`), and `socpuppet.pump.pump` runs the platform and keeps up with it: it waits on the wall while the drive's CPU sleeps, and looks every short while as it works. ⚠️ From `start()` on, Linux's driver is talking to the drive, so the platform has to be pumped: a drive that is not answering is one Linux waits 30 s for, at each command.
- ⚠️ **Let go before the end.** A platform that ends while Linux's driver holds its drive leaves the driver waiting for answers that never come, and the program's last `close` waiting for the driver: half a minute for each command it was owed. Unbind the driver first, while the platform is still pumped, with `echo <function> | sudo tee /sys/bus/pci/devices/<function>/driver/unbind`. The driver shuts the drive down as it goes, which has the SSD's firmware save its table. `socpuppet drive` says the line to type when Ctrl-C finds Linux still holding the drive, and waits for it; a second Ctrl-C ends it anyway, as a card is pulled from its slot.

## What it leaves out

- **The endpoint's configuration space and MSI-X table.** pciem's kernel side plays them, with the IDs and class code given, a BAR0 of `function_size` and an MSI-X table in a BAR2 of its own, so the endpoint's command register, its bus-master gating and its master-abort bit are not here.
- **More than one interrupt.** pciem's virtual bus gives the device one legacy interrupt, so every vector reaches the same one, and Linux's `nvme` driver makes one I/O queue ([upstream.md](../upstream.md#the-virtual-root-has-no-msi-domain-so-a-device-gets-one-interrupt)).
- **The link, and its trace.** There is no link between the host and the function, so nothing is timed for one and the [tracer](tracer.md) has nothing to show of it.
- **One clock.** The host runs on the wall and the drive on the simulation's clock, which the pump keeps from running ahead of the wall while the drive is idle. A drive that works runs slower than the real one, and Linux's timeouts are on the wall: the SSD with its Zephyr firmware answers well inside them.
- **A host's writes beyond the ring's 256.** A write that finds the ring full is lost, with a warning in the kernel's log ([upstream.md](../upstream.md#a-full-ring-drops-the-hosts-writes)). The pump drains it whenever pciem says it has posted, and no test has seen it full.
- **Writes the kernel does not make through its own mapping.** pciem traces only those, so root writing `/sys/bus/pci/devices/<function>/resource0` changes what the host reads and the function never hears of it.

## Where it comes from

💡 Borrowed. The bus is Linux's own and the slot is [pciem](https://github.com/cakehonolulu/pciem)'s, at `f80bbb71`, built by `tools/build_pciem.py`. socpuppet's side is `src/socpuppet/models/pciem_host.h`, a SystemC module, with what it decides in plain C++ in `src/socpuppet/core/pciem_host_logic.h`, and the calls to `/dev/pciem` behind a small interface in `src/socpuppet/core/pciem_device.h`, so its tests (`tests/cpp/platform/pciem_host_test.cpp`) use a fake device and need no root. The calls themselves are in `src/socpuppet/core/pciem_device.cpp`, the one file that includes pciem's header, which is GPL-2.0-only and needs C++23, so it is built in a library of its own with no SystemC; its ring is tested in `tests/cpp/unit/pciem_ring_test.cpp`.

What socpuppet relies on of pciem is its contract suite, `tests/python/test_pciem_contract.py`, which runs where 🩺 the doctor's `pciem` area is well: the host reads what the drive says, a register nobody wrote reads as zero, the registers Linux's driver writes reach the drive as written, a block written reads back the same, and letting go shuts the drive down. `tests/python/test_m31_exit.py` is the whole of it: Linux formats and mounts the SSD with its Zephyr firmware, writes a file, and Python reads it back out of the NAND. The real-host spike found the way ([history/real-host-spike.md](../history/real-host-spike.md)), and what pciem gets wrong is in [upstream.md](../upstream.md#pciem).
