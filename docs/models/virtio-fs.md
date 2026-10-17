# 🎭 Virtio file system device

`sp.VirtioFs(tag="socpuppet", directory=...)` · C++ `socpuppet::VirtioFs` · registry name `virtio_fs`

## What it stands for

🎭 A stand-in (a simplified model) for a shared directory: QEMU's `vhost-user-fs-device`, with Python in the place of the `virtiofsd` daemon behind it. 🎓 Device 26 in the specification (section 5.11). The driver mounts the share by its tag and talks to it in FUSE, Linux's protocol for a file system served by a program: each chain is one request, its readable buffers the request and its writable ones the room for the answer.

## What it does

```python
fs = platform.add("fs", sp.VirtioFs(tag="spam", directory="/tmp/share"))
bus.map(fs.cpu, base=0x1000_5000)
platform.connect(fs.dma, bus.add_input())
platform.connect(fs.irq, aplic.source22)
```

- **Knows no FUSE.** The device hands each request's bytes to whatever serves the share and writes back what that gives, the split QEMU makes between its device and the daemon. 🧵 With a `directory`, what serves it is `socpuppet.fuse.Directory`, called through the Python executor on Python's own stack, a request at a time. With none, every request comes back empty.
- **Has two queues:** the high-priority one, which the specification gives `FORGET`, and one request queue, and answers on either the same way: EDK2 sends its `FORGET`s on the request queue, and Zephyr sets the high-priority queue up with no entries. The tag and the number of request queues, one, are its configuration.
- **Serves a real directory.** `socpuppet.fuse.Directory` answers FUSE 7.31, the union of what Zephyr's and EDK2's clients ask: `INIT`, `LOOKUP`, `FORGET`, `GETATTR`, `SETATTR`, `OPEN`, `OPENDIR`, `READ`, `WRITE`, `CREATE`, `MKDIR`, `UNLINK`, `RMDIR`, `RENAME` and `RENAME2`, `READDIR` and `READDIRPLUS`, `LSEEK`, `STATFS`, and the releases, flushes and syncs, which have nothing to do since it holds nothing open. Anything else is `ENOSYS`, and a request that does not parse is `EINVAL`.

⚠️ Firmware may change anything under `directory`: create, write, rename and remove. Nothing outside it is reachable: `..` stops at the top, a link that leads out is left out of listings, and a node that has come to lead out is refused. A link that stays inside is followed. Errors are answered in Linux's numbers whatever the host's are, and so are the open flags read.

## What it leaves out

More than one request queue, the notification queue (`F_NOTIFICATION`), and the DAX window that maps files straight into the guest's memory. Of FUSE: locks, extended attributes, hard and symbolic links made by the client, and `mmap`.

## In a devicetree

`compatible = "virtio,mmio"` alone, in both dialects, and the alias `virtiofs0`: Zephyr's client mounts the transport's device itself, and a program finds it by the alias. Linux finds the share by the tag the device gives.

## Who has driven it

🧵 `sp.VirtioFsHost`; Zephyr's `subsys/fs/virtiofs`, through `samples/subsys/fs/virtiofs` unchanged (an overlay of ours gives the share's node the label the sample asks for), which lists, reads and creates; and EDK2's `VirtioFsDxe`, with one patch (`cmake/patches/edk2-virtiofs-sets-its-queue-size.patch`), whose shell mounts the share by its tag, lists it, reads it and writes to it. Linux's `virtiofs` is not in RISC-V's `defconfig` and has not run against it.
