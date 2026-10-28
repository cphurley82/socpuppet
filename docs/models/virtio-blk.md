# 🎭 Virtio block device

`sp.VirtioBlk(blocks=...)` · C++ `socpuppet::VirtioBlk` · registry name `virtio_blk`

## What it stands for

🎭 A stand-in (a simplified model) for a disk: QEMU's `virtio-blk-device`, the disk a `virt` machine's kernel most often mounts its root on. 🎓 Device 2 in the specification (section 5.2): one queue, and each chain one request, a 16-byte header the device reads (the request's kind and its first sector), the data, and a status byte the device writes last.

## What it does

```python
blk = platform.add("blk", sp.VirtioBlk(blocks=2048))     # 1 MiB of 512-byte sectors
bus.map(blk.cpu, base=0x1000_3000)
platform.connect(blk.dma, bus.add_input())

platform.build()
blk.load(fat_image)          # an image, from sector 0
platform.run(sp.ms(100))
contents = blk.contents      # every sector, as bytes
```

| Request | What the device does | Status |
|---|---|---|
| `IN` (0) | Reads whole sectors into the data buffers | `OK`, or `IOERR` past the end or for less than a sector |
| `OUT` (1) | Writes whole sectors from the data buffers | the same |
| `FLUSH` (4) | Nothing: the disk is RAM, so nothing is waiting | `OK` |
| `GET_ID` (8) | Writes `socpuppet`, padded with zeros, in as much of 20 bytes as there is room for | `OK` |
| anything else | Nothing | `UNSUPP` |

- **Offers `F_FLUSH`,** since a flush is answered. With no `CONFIG_WCE`, Linux takes that to mean a write-back cache and flushes where it needs to.
- **Has its capacity in its configuration,** in sectors, read-only. A driver's write there is dropped.
- **Keeps only what is written.** The disk is a `RamBlockStore`, the NVMe models' store: a sector takes memory once written. `contents` is every sector, written or not, so a large disk makes a large `bytes`.
- **Refuses an image larger than the disk** with a `ValueError`, and a request with no header or no room for its status comes back with nothing written.

## What it leaves out

More than one queue (`F_MQ`), discard and write-zeroes, read-only (`F_RO`), and the optional sizes and geometry (`F_SIZE_MAX`, `F_SEG_MAX`, `F_GEOMETRY`, `F_BLK_SIZE`, `F_TOPOLOGY`). ⚠️ With no `F_SEG_MAX`, Linux sends one data segment a request, which is slower and still correct.

## In a devicetree

`compatible = "virtio,mmio"` alone, in both dialects: Zephyr has no virtio disk driver, so there is no child to bind. Zephyr's transport still finds the slot at boot and leaves it alone.

## Who has driven it

🧵 `sp.VirtioBlkHost`; EDK2's `VirtioBlkDxe`, which with EDK2's FAT driver mounts an image Python made with `tests/python/fat_image.py` as `FS0:`, reads it and writes to it. 💡 EDK2's boot manager tries the disk before its shell, looking for `\EFI\BOOT\BOOTRISCV64.EFI`: a disk with that file is booted without anyone typing. 🐧 Linux's `virtio_blk` (`VIRTIO_BLK`, built in) mounts its root filesystem from it, an ext4 image `firmware/build.py` makes (`root=/dev/vda`), and `uname -a` at the prompt is the boot's test (`tests/python/test_linux_boots.py`).
