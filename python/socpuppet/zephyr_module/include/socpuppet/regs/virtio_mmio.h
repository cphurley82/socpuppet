/*
 * Virtio over MMIO: the registers.
 *
 * The register block every virtio device of socpuppet's sits behind: how a
 * driver finds out what the device is, agrees on features with it, tells it
 * where the virtqueues are, rings its doorbell and acknowledges its
 * interrupt. The device's own configuration starts at `0x100`.
 *
 * Generated from regs/virtio_mmio.rdl by tools/regs.py. Do not edit: change
 * the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_VIRTIO_MMIO_H_
#define SOCPUPPET_REGS_VIRTIO_MMIO_H_

/* How many bytes of address space the block takes. */
#define VIRTIO_MMIO_SIZE 0x200U

/*
 * Says this is a virtio device: the bytes of `virt`, read as a little-endian
 * word.
 */
#define VIRTIO_MMIO_MAGIC_VALUE          0x000U
#define VIRTIO_MMIO_MAGIC_VALUE_AT_RESET 0x74726976U

/*
 * Which layout of this register block the device speaks. Two is the modern
 * one; one was the legacy layout, which no device here speaks.
 */
#define VIRTIO_MMIO_VERSION          0x004U
#define VIRTIO_MMIO_VERSION_AT_RESET 0x00000002U

/*
 * What the device is, by the specification's numbering: 1 a network card, 2 a
 * block device, 3 a console, 4 an entropy source, 26 a file system. Zero
 * means there is no device in this slot.
 */
#define VIRTIO_MMIO_DEVICE_ID 0x008U

/* Who made the device. socpuppet's is `0x5350`, the letters SP. */
#define VIRTIO_MMIO_VENDOR_ID 0x00CU

/*
 * Thirty-two of the feature bits the device offers: which thirty-two is what
 * `DEVICE_FEATURES_SEL` says.
 */
#define VIRTIO_MMIO_DEVICE_FEATURES 0x010U

/*
 * Which word of the device's feature bits `DEVICE_FEATURES` shows: zero for
 * bits 0 to 31, one for bits 32 to 63.
 */
#define VIRTIO_MMIO_DEVICE_FEATURES_SEL 0x014U

/*
 * Thirty-two of the feature bits the driver accepts, into the word
 * `DRIVER_FEATURES_SEL` names. The driver may accept only what was offered,
 * and must accept bit 32, `VERSION_1`. The spec has the driver only write it;
 * a read gives the word back, as QEMU's device does, because Zephyr's
 * transport reads it to set one bit.
 */
#define VIRTIO_MMIO_DRIVER_FEATURES 0x020U

/* Which word of the driver's feature bits `DRIVER_FEATURES` writes. */
#define VIRTIO_MMIO_DRIVER_FEATURES_SEL 0x024U

/*
 * Which virtqueue the registers from `QUEUE_NUM_MAX` to `QUEUE_DEVICE_HIGH`
 * are about.
 */
#define VIRTIO_MMIO_QUEUE_SEL 0x030U

/*
 * The most entries the selected virtqueue can have. Zero means the queue does
 * not exist.
 */
#define VIRTIO_MMIO_QUEUE_NUM_MAX 0x034U

/*
 * How many entries the driver gave the selected virtqueue: at most
 * `QUEUE_NUM_MAX`, and a power of two.
 */
#define VIRTIO_MMIO_QUEUE_NUM 0x038U

/*
 * Whether the selected virtqueue is in use. The driver writes a one once the
 * queue's size and addresses are set, and a zero to take the queue away.
 */
#define VIRTIO_MMIO_QUEUE_READY       0x044U
#define VIRTIO_MMIO_QUEUE_READY_READY (1U << 0)

/*
 * The doorbell: the driver writes the number of a virtqueue it has put
 * buffers in, and the device goes and looks.
 */
#define VIRTIO_MMIO_QUEUE_NOTIFY 0x050U

/*
 * Why the interrupt line is high. The line stays high until every set bit is
 * acknowledged.
 */
#define VIRTIO_MMIO_INTERRUPT_STATUS               0x060U
/* The device used a buffer in some virtqueue. */
#define VIRTIO_MMIO_INTERRUPT_STATUS_USED_BUFFER   (1U << 0)
/* The device's configuration changed. */
#define VIRTIO_MMIO_INTERRUPT_STATUS_CONFIG_CHANGE (1U << 1)

/*
 * Acknowledges interrupts: writing a one to a bit clears that bit of
 * `INTERRUPT_STATUS`.
 */
#define VIRTIO_MMIO_INTERRUPT_ACK               0x064U
/* Clears `USED_BUFFER`. */
#define VIRTIO_MMIO_INTERRUPT_ACK_USED_BUFFER   (1U << 0)
/* Clears `CONFIG_CHANGE`. */
#define VIRTIO_MMIO_INTERRUPT_ACK_CONFIG_CHANGE (1U << 1)

/*
 * How far the driver has got with the device. It sets the bits one after
 * another as it goes; writing zero resets the device.
 */
#define VIRTIO_MMIO_STATUS                    0x070U
/* The driver has seen the device. */
#define VIRTIO_MMIO_STATUS_ACKNOWLEDGE        (1U << 0)
/* The driver knows how to drive it. */
#define VIRTIO_MMIO_STATUS_DRIVER             (1U << 1)
/* The driver is set up and the device may use its queues. */
#define VIRTIO_MMIO_STATUS_DRIVER_OK          (1U << 2)
/*
 * The driver has written its features. The device keeps the bit only if it
 * can live with them; the driver reads it back to find out.
 */
#define VIRTIO_MMIO_STATUS_FEATURES_OK        (1U << 3)
/* The device has hit an error it cannot recover from and wants a reset. */
#define VIRTIO_MMIO_STATUS_DEVICE_NEEDS_RESET (1U << 6)
/* The driver has given up on the device. */
#define VIRTIO_MMIO_STATUS_FAILED             (1U << 7)

/*
 * The low 32 bits of the address of the selected virtqueue's descriptor
 * table.
 */
#define VIRTIO_MMIO_QUEUE_DESC_LOW 0x080U

/*
 * The high 32 bits of the address of the selected virtqueue's descriptor
 * table.
 */
#define VIRTIO_MMIO_QUEUE_DESC_HIGH 0x084U

/*
 * The low 32 bits of the address of the selected virtqueue's driver area, the
 * available ring.
 */
#define VIRTIO_MMIO_QUEUE_DRIVER_LOW 0x090U

/*
 * The high 32 bits of the address of the selected virtqueue's driver area,
 * the available ring.
 */
#define VIRTIO_MMIO_QUEUE_DRIVER_HIGH 0x094U

/*
 * The low 32 bits of the address of the selected virtqueue's device area, the
 * used ring.
 */
#define VIRTIO_MMIO_QUEUE_DEVICE_LOW 0x0A0U

/*
 * The high 32 bits of the address of the selected virtqueue's device area,
 * the used ring.
 */
#define VIRTIO_MMIO_QUEUE_DEVICE_HIGH 0x0A4U

/*
 * Which shared memory region the three registers after this one are about. No
 * device here has one.
 */
#define VIRTIO_MMIO_SHM_SEL 0x0ACU

/*
 * The low 32 bits of the selected shared memory region's length. All ones,
 * with `SHM_LEN_HIGH`, says there is no such region.
 */
#define VIRTIO_MMIO_SHM_LEN_LOW          0x0B0U
#define VIRTIO_MMIO_SHM_LEN_LOW_AT_RESET 0xFFFFFFFFU

/* The high 32 bits of the selected shared memory region's length. */
#define VIRTIO_MMIO_SHM_LEN_HIGH          0x0B4U
#define VIRTIO_MMIO_SHM_LEN_HIGH_AT_RESET 0xFFFFFFFFU

/* The low 32 bits of the selected shared memory region's address. */
#define VIRTIO_MMIO_SHM_BASE_LOW 0x0B8U

/* The high 32 bits of the selected shared memory region's address. */
#define VIRTIO_MMIO_SHM_BASE_HIGH 0x0BCU

/*
 * Counts up each time the device's configuration changes, so that a driver
 * reading several words of it can tell whether they belong together.
 */
#define VIRTIO_MMIO_CONFIG_GENERATION 0x0FCU

/*
 * Where the device's own configuration starts: a block device's capacity, a
 * network card's MAC address, a file system's tag. Its layout is the
 * device's, and it is read and written at any width.
 */
#define VIRTIO_MMIO_CONFIG 0x100U

#endif /* SOCPUPPET_REGS_VIRTIO_MMIO_H_ */
