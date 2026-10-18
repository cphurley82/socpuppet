# 🎭 Virtio 9P transport

`sp.Virtio9p(tag="socpuppet", directory=...)` · C++ `socpuppet::Virtio9p` · registry name `virtio_9p`

## What it stands for

🎭 A stand-in (a simplified model) for a shared directory: QEMU's `virtio-9p-device`, with Python in the place of QEMU's file server. 🎓 Device 9 in the specification's list, which has no section for it, so the layout is Linux's (`include/uapi/linux/virtio_9p.h`). The driver mounts the share by its tag and talks to it in 9P2000.L, the dialect of Plan 9's file protocol that Linux's client speaks: each chain is one message, its readable buffers the T-message and its writable ones the room for the R-message. It is the shared directory 🐧 Linux mounts; the [file system device](virtio-fs.md) beside it is the one Zephyr and EDK2 mount, and both serve the same directory by the same tag.

## What it does

```python
ninep = platform.add("ninep", sp.Virtio9p(tag="spam", directory="/tmp/share"))
bus.map(ninep.cpu, base=0x1000_6000)
platform.connect(ninep.dma, bus.add_input())
platform.connect(ninep.irq, aplic.source23)
```

- **Knows no 9P.** The device hands each message's bytes to whatever serves the share and writes back what that gives, as the file system device does with FUSE. 🧵 With a `directory`, what serves it is `socpuppet.ninep.Directory`, called through the Python executor on Python's own stack, a message at a time. With none, every message comes back empty.
- **Has one queue and one feature**, `VIRTIO_9P_MOUNT_TAG`, which says the configuration holds a tag: Linux's driver will not take a device without it. The configuration is the tag's length in two bytes and then the tag, at most 254 bytes, which is what the transport's 256 bytes of configuration hold.
- **Serves a real directory.** `socpuppet.ninep.Directory` answers what Linux's client sends to mount, list, read, write and create: `Tversion`, `Tattach`, `Tflush`, `Twalk`, `Tlopen`, `Tlcreate`, `Tread`, `Twrite`, `Tclunk`, `Tgetattr`, `Tsetattr`, `Treaddir`, `Tmkdir`, `Tunlinkat`, `Trenameat`, `Tsymlink`, `Treadlink`, `Tstatfs` and `Tfsync`. Anything else is `Rlerror` with `EOPNOTSUPP`, which Linux's client takes as "do without".

⚠️ Firmware may change anything under `directory`: create, write, rename and remove. Nothing outside it is reachable: `..` stops at the top, a walk through a link that leads out is refused, and a fid that has come to lead out is refused when next used. Errors are answered in Linux's numbers whatever the host's are, and so are the open flags read.

## What it leaves out

Of 9P2000.L: `Tremove`, `Trename` and `Tlink` (Linux's client uses the at-forms, and a hard link is refused), locks, extended attributes and `Tmknod`. Linux's client sends a large read's or write's data in pages of their own after the header, which the device reads and writes as one run of bytes, as it does every chain.

## In a devicetree

`compatible = "virtio,mmio"` alone, in both dialects. Linux finds the share by the tag the device gives; Zephyr has no 9P client.

## Who has driven it

🧵 `sp.Virtio9pHost`, which attaches, opens a file and reads it.
