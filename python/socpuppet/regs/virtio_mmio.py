"""Virtio over MMIO: the registers.

The register block every virtio device of socpuppet's sits behind: how a
driver finds out what the device is, agrees on features with it, tells it
where the virtqueues are, rings its doorbell and acknowledges its interrupt.
The device's own configuration starts at `0x100`.

Generated from regs/virtio_mmio.rdl by tools/regs.py. Do not edit: change the
register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x200

#: Says this is a virtio device: the bytes of `virt`, read as a little-endian
#: word.
MAGIC_VALUE = 0x000
MAGIC_VALUE_AT_RESET = 0x74726976

#: Which layout of this register block the device speaks. Two is the modern
#: one; one was the legacy layout, which no device here speaks.
VERSION = 0x004
VERSION_AT_RESET = 0x00000002

#: What the device is, by the specification's numbering: 1 a network card, 2 a
#: block device, 3 a console, 4 an entropy source, 26 a file system. Zero
#: means there is no device in this slot.
DEVICE_ID = 0x008

#: Who made the device. socpuppet's is `0x5350`, the letters SP.
VENDOR_ID = 0x00C

#: Thirty-two of the feature bits the device offers: which thirty-two is what
#: `DEVICE_FEATURES_SEL` says.
DEVICE_FEATURES = 0x010

#: Which word of the device's feature bits `DEVICE_FEATURES` shows: zero for
#: bits 0 to 31, one for bits 32 to 63.
DEVICE_FEATURES_SEL = 0x014

#: Thirty-two of the feature bits the driver accepts, into the word
#: `DRIVER_FEATURES_SEL` names. The driver may accept only what was offered,
#: and must accept bit 32, `VERSION_1`.
DRIVER_FEATURES = 0x020

#: Which word of the driver's feature bits `DRIVER_FEATURES` writes.
DRIVER_FEATURES_SEL = 0x024

#: Which virtqueue the registers from `QUEUE_NUM_MAX` to `QUEUE_DEVICE_HIGH`
#: are about.
QUEUE_SEL = 0x030

#: The most entries the selected virtqueue can have. Zero means the queue does
#: not exist.
QUEUE_NUM_MAX = 0x034

#: How many entries the driver gave the selected virtqueue: at most
#: `QUEUE_NUM_MAX`, and a power of two.
QUEUE_NUM = 0x038

#: Whether the selected virtqueue is in use. The driver writes a one once the
#: queue's size and addresses are set, and a zero to take the queue away.
QUEUE_READY = 0x044
QUEUE_READY_READY = 1 << 0

#: The doorbell: the driver writes the number of a virtqueue it has put
#: buffers in, and the device goes and looks.
QUEUE_NOTIFY = 0x050

#: Why the interrupt line is high. The line stays high until every set bit is
#: acknowledged.
INTERRUPT_STATUS = 0x060
#: The device used a buffer in some virtqueue.
INTERRUPT_STATUS_USED_BUFFER = 1 << 0
#: The device's configuration changed.
INTERRUPT_STATUS_CONFIG_CHANGE = 1 << 1

#: Acknowledges interrupts: writing a one to a bit clears that bit of
#: `INTERRUPT_STATUS`.
INTERRUPT_ACK = 0x064
#: Clears `USED_BUFFER`.
INTERRUPT_ACK_USED_BUFFER = 1 << 0
#: Clears `CONFIG_CHANGE`.
INTERRUPT_ACK_CONFIG_CHANGE = 1 << 1

#: How far the driver has got with the device. It sets the bits one after
#: another as it goes; writing zero resets the device.
STATUS = 0x070
#: The driver has seen the device.
STATUS_ACKNOWLEDGE = 1 << 0
#: The driver knows how to drive it.
STATUS_DRIVER = 1 << 1
#: The driver is set up and the device may use its queues.
STATUS_DRIVER_OK = 1 << 2
#: The driver has written its features. The device keeps the bit only if it
#: can live with them; the driver reads it back to find out.
STATUS_FEATURES_OK = 1 << 3
#: The device has hit an error it cannot recover from and wants a reset.
STATUS_DEVICE_NEEDS_RESET = 1 << 6
#: The driver has given up on the device.
STATUS_FAILED = 1 << 7

#: The low 32 bits of the address of the selected virtqueue's descriptor
#: table.
QUEUE_DESC_LOW = 0x080

#: The high 32 bits of the address of the selected virtqueue's descriptor
#: table.
QUEUE_DESC_HIGH = 0x084

#: The low 32 bits of the address of the selected virtqueue's driver area, the
#: available ring.
QUEUE_DRIVER_LOW = 0x090

#: The high 32 bits of the address of the selected virtqueue's driver area,
#: the available ring.
QUEUE_DRIVER_HIGH = 0x094

#: The low 32 bits of the address of the selected virtqueue's device area, the
#: used ring.
QUEUE_DEVICE_LOW = 0x0A0

#: The high 32 bits of the address of the selected virtqueue's device area,
#: the used ring.
QUEUE_DEVICE_HIGH = 0x0A4

#: Which shared memory region the three registers after this one are about. No
#: device here has one.
SHM_SEL = 0x0AC

#: The low 32 bits of the selected shared memory region's length. All ones,
#: with `SHM_LEN_HIGH`, says there is no such region.
SHM_LEN_LOW = 0x0B0
SHM_LEN_LOW_AT_RESET = 0xFFFFFFFF

#: The high 32 bits of the selected shared memory region's length.
SHM_LEN_HIGH = 0x0B4
SHM_LEN_HIGH_AT_RESET = 0xFFFFFFFF

#: The low 32 bits of the selected shared memory region's address.
SHM_BASE_LOW = 0x0B8

#: The high 32 bits of the selected shared memory region's address.
SHM_BASE_HIGH = 0x0BC

#: Counts up each time the device's configuration changes, so that a driver
#: reading several words of it can tell whether they belong together.
CONFIG_GENERATION = 0x0FC

#: Where the device's own configuration starts: a block device's capacity, a
#: network card's MAC address, a file system's tag. Its layout is the
#: device's, and it is read and written at any width.
CONFIG = 0x100
