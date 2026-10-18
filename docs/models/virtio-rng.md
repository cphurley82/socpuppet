# 🎭 Virtio entropy device

`sp.VirtioRng(seed=1)` · C++ `socpuppet::VirtioRng` · registry name `virtio_rng`

## What it stands for

🎭 A stand-in (a simplified model) for a hardware random number generator, the block a kernel stirs into its entropy pool. 🎓 It is the smallest virtio device there is (device 4 in the specification, section 5.4): one virtqueue, no features and no configuration. The driver hands it empty buffers and it fills them with random bytes. QEMU calls it `virtio-rng-device`.

## What it does

```python
rng = platform.add("rng", sp.VirtioRng(seed=7))
bus.map(rng.cpu, base=0x1000_1000)
platform.connect(rng.dma, bus.add_input())       # how it reaches the driver's memory
platform.connect(rng.irq, aplic.source18)        # optional: a driver may poll
```

- **Fills every buffer it is handed, whole,** and gives each back with its length, as soon as the doorbell rings.
- **Is repeatable.** The bytes come from a generator (`std::mt19937_64`) seeded with `seed`: the same seed gives the same bytes, run after run, which is what a test wants and what a real generator is not. A reset does not start the sequence again.
- **Is behind the virtio-mmio transport,** with its registers, interrupt and DMA as [that page](virtio-mmio.md) says.

## What it leaves out

- **Entropy.** The bytes are as random as a seeded generator, which is no more random than its seed. Nothing here is for keys.
- **A rate.** A buffer of any size is filled at once.

## In a devicetree

`compatible = "virtio,mmio"` for its slot, in both dialects. In Zephyr's, the entropy driver binds to a child node, `virtio-entropy { compatible = "virtio,device4"; }`, which is also `chosen` as `zephyr,entropy`. Linux reads the device's kind from its `DEVICE_ID` register and needs no child.

## Who has driven it

🧵 `sp.VirtioRngHost` ([virtio-host.md](virtio-host.md)); Zephyr's `drivers/entropy/entropy_virtio.c`, through `tests/drivers/entropy/api`; and EDK2's `VirtioRngDxe`, whose `EFI_RNG_PROTOCOL` the shell's `dh -p Rng` finds on it. 🐧 Linux's `virtio-rng` (`HW_RANDOM_VIRTIO`, built into RISC-V's `defconfig`) makes it `/dev/hwrng`, and the bytes read there are the seeded stream's, as `tests/python/test_m20_exit.py` checks with a port of the generator; 🎓 not its start, since the kernel's own thread draws from the device first, to stir into its pool.
