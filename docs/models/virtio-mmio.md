# Virtio over MMIO

Not a component you can place: the transport that every virtio device of socpuppet's sits behind. C++ `socpuppet::VirtioMmio<Device>` · register map `regs/virtio_mmio.rdl`

## What it stands for

🎓 **Virtio** is the family of devices a virtual machine offers its guest when it does not pretend to be real hardware: a block device, a network card, a console and a few more, each a small register block and rings of descriptors in the guest's memory. **`virtio-mmio`** is the transport where that register block sits on the bus at an address the devicetree gives, with one interrupt line, which is the one that fits a SoC with no PCIe between the CPU and the device. Every Linux drives it, and so does QEMU's `virt` machine.

No real SoC has one. socpuppet's are 🎭 stand-ins: they hold a real block's place so that the rest of the cast can rehearse, and tell a kernel that will not boot from a device that does not work. The devices are the entropy source, the console, the block device, the network card and the file system, each with a page of its own.

## The registers

Each is 32 bits wide and read or written whole, except the device's configuration from `0x100`, which is read and written at any width. The layout is version 2 of the specification's, register for register.

<!-- regs:virtio_mmio start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x000` | `MAGIC_VALUE` | read | Says this is a virtio device: the bytes of `virt`, read as a little-endian word. At reset: `0x74726976`. |
| `0x004` | `VERSION` | read | Which layout of this register block the device speaks. Two is the modern one; one was the legacy layout, which no device here speaks. At reset: `0x00000002`. |
| `0x008` | `DEVICE_ID` | read | What the device is, by the specification's numbering: 1 a network card, 2 a block device, 3 a console, 4 an entropy source, 26 a file system. Zero means there is no device in this slot. |
| `0x00C` | `VENDOR_ID` | read | Who made the device. socpuppet's is `0x5350`, the letters SP. |
| `0x010` | `DEVICE_FEATURES` | read | Thirty-two of the feature bits the device offers: which thirty-two is what `DEVICE_FEATURES_SEL` says. |
| `0x014` | `DEVICE_FEATURES_SEL` | write | Which word of the device's feature bits `DEVICE_FEATURES` shows: zero for bits 0 to 31, one for bits 32 to 63. |
| `0x020` | `DRIVER_FEATURES` | read, write | Thirty-two of the feature bits the driver accepts, into the word `DRIVER_FEATURES_SEL` names. The driver may accept only what was offered, and must accept bit 32, `VERSION_1`. The spec has the driver only write it; a read gives the word back, as QEMU's device does, because Zephyr's transport reads it to set one bit. |
| `0x024` | `DRIVER_FEATURES_SEL` | write | Which word of the driver's feature bits `DRIVER_FEATURES` writes. |
| `0x030` | `QUEUE_SEL` | write | Which virtqueue the registers from `QUEUE_NUM_MAX` to `QUEUE_DEVICE_HIGH` are about. |
| `0x034` | `QUEUE_NUM_MAX` | read | The most entries the selected virtqueue can have. Zero means the queue does not exist. |
| `0x038` | `QUEUE_NUM` | write | How many entries the driver gave the selected virtqueue: at most `QUEUE_NUM_MAX`, and a power of two. |
| `0x044` | `QUEUE_READY` | read, write | Whether the selected virtqueue is in use. The driver writes a one once the queue's size and addresses are set, and a zero to take the queue away. Bit 0 `READY`. |
| `0x050` | `QUEUE_NOTIFY` | write | The doorbell: the driver writes the number of a virtqueue it has put buffers in, and the device goes and looks. |
| `0x060` | `INTERRUPT_STATUS` | read | Why the interrupt line is high. The line stays high until every set bit is acknowledged. Bit 0 `USED_BUFFER`: The device used a buffer in some virtqueue. Bit 1 `CONFIG_CHANGE`: The device's configuration changed. |
| `0x064` | `INTERRUPT_ACK` | write | Acknowledges interrupts: writing a one to a bit clears that bit of `INTERRUPT_STATUS`. Bit 0 `USED_BUFFER`: Clears `USED_BUFFER`. Bit 1 `CONFIG_CHANGE`: Clears `CONFIG_CHANGE`. |
| `0x070` | `STATUS` | read, write | How far the driver has got with the device. It sets the bits one after another as it goes; writing zero resets the device. Bit 0 `ACKNOWLEDGE`: The driver has seen the device. Bit 1 `DRIVER`: The driver knows how to drive it. Bit 2 `DRIVER_OK`: The driver is set up and the device may use its queues. Bit 3 `FEATURES_OK`: The driver has written its features. The device keeps the bit only if it can live with them; the driver reads it back to find out. Bit 6 `DEVICE_NEEDS_RESET`: The device has hit an error it cannot recover from and wants a reset. Bit 7 `FAILED`: The driver has given up on the device. |
| `0x080` | `QUEUE_DESC_LOW` | write | The low 32 bits of the address of the selected virtqueue's descriptor table. |
| `0x084` | `QUEUE_DESC_HIGH` | write | The high 32 bits of the address of the selected virtqueue's descriptor table. |
| `0x090` | `QUEUE_DRIVER_LOW` | write | The low 32 bits of the address of the selected virtqueue's driver area, the available ring. |
| `0x094` | `QUEUE_DRIVER_HIGH` | write | The high 32 bits of the address of the selected virtqueue's driver area, the available ring. |
| `0x0A0` | `QUEUE_DEVICE_LOW` | write | The low 32 bits of the address of the selected virtqueue's device area, the used ring. |
| `0x0A4` | `QUEUE_DEVICE_HIGH` | write | The high 32 bits of the address of the selected virtqueue's device area, the used ring. |
| `0x0AC` | `SHM_SEL` | write | Which shared memory region the three registers after this one are about. No device here has one. |
| `0x0B0` | `SHM_LEN_LOW` | read | The low 32 bits of the selected shared memory region's length. All ones, with `SHM_LEN_HIGH`, says there is no such region. At reset: `0xFFFFFFFF`. |
| `0x0B4` | `SHM_LEN_HIGH` | read | The high 32 bits of the selected shared memory region's length. At reset: `0xFFFFFFFF`. |
| `0x0B8` | `SHM_BASE_LOW` | read | The low 32 bits of the selected shared memory region's address. |
| `0x0BC` | `SHM_BASE_HIGH` | read | The high 32 bits of the selected shared memory region's address. |
| `0x0FC` | `CONFIG_GENERATION` | read | Counts up each time the device's configuration changes, so that a driver reading several words of it can tell whether they belong together. |
| `0x100` | `CONFIG` | read, write | Where the device's own configuration starts: a block device's capacity, a network card's MAC address, a file system's tag. Its layout is the device's, and it is read and written at any width. |

<!-- regs:virtio_mmio end -->

## What it does

Each device's page says what the device does; this is what they share. `socpuppet::VirtioMmio<Device>` is a shell of SystemC around plain C++: `VirtioMmioLogic` is the register block, `Virtqueue` walks a split virtqueue in the driver's memory, and a `VirtioDevice` is what one kind of device does with a chain.

- **Agrees on features.** The device offers its own bits and `VERSION_1` (bit 32), which the transport insists on. `FEATURES_OK` stays set only if the driver accepted what was offered and no more, and `VERSION_1` among it.
- **Lays out queues where the driver says.** Each queue's size and the three parts' 64-bit addresses, anywhere in the driver's memory, above 4 GiB as well. A queue of more entries than `QUEUE_NUM_MAX` (256) is refused with an error response, and one of none is never ready: Zephyr's virtio-fs driver sets its unused queue up that way on purpose.
- **Works a delta cycle after the doorbell.** A write to `QUEUE_NOTIFY` only marks the queue; the device walks it in a process of its own, a delta cycle later, so that its reads and writes of the driver's memory never happen inside the CPU's access. That is the [command device](command-device.md) shell the DMA engine has, through `dma`, a bus master port.
- **Hands each chain over whole.** The walker follows a chain's `next` links, splits it into the buffers the device reads and the ones it writes, and refuses a chain that loops. Reads and writes go across as many buffers as the chain has, so a driver may split a request where it likes.
- **Interrupts while a used buffer waits.** `irq` is high while `INTERRUPT_STATUS` has a bit set, and `INTERRUPT_ACK` lowers it. A device that keeps a chain (the console's and the network card's receive buffers) gives it back later, and the transport raises the line for that too.
- **Resets on a write of zero to `STATUS`.** Everything the driver told the device is forgotten, and the device drops the chains it holds.
- **Keeps the configuration read-only.** Reads at any width from `0x100`; a write is handed to the device, which drops it unless it has a field a driver may write. None of the five has.

## What it leaves out

- **The legacy layout,** version 1 of this register block, which only old drivers speak.
- **Packed virtqueues, indirect descriptors and event indices** (`F_RING_PACKED`, `F_INDIRECT_DESC`, `F_EVENT_IDX`): the split ring as the specification first had it, which every driver falls back to.
- **Shared memory regions** (`SHM_SEL`, `SHM_LEN`, read as none) and notification data.
- **A configuration change interrupt,** which no device here raises, since none changes its configuration.

## Under the hood

- `regs/virtio_mmio.rdl` is the register map, in SystemRDL. `tools/regs.py` writes the table above from it, and the C header and the Python module that the rest go by.
