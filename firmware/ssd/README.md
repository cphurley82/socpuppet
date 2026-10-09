# The SSD's firmware 🧦

A Zephyr application for the board `socpuppet_ssd`: what runs on the RISC-V core inside socpuppet's SSD and makes it a drive. The SSD's hardware keeps the host's queues and moves the data, and this decides everything else: when the controller is ready, what each command means, whether the host may have what it asks for, and where on the NAND each of the drive's blocks really is.

| File | What is in it |
|---|---|
| `src/main.c` | The loop: wait for the NVMe frontend, see to a reset or an enable, deal with a command. |
| `src/admin.c` | The admin commands: Identify, Set Features, creating an I/O queue. |
| `src/io.c` | Read, Write and Flush. |
| `src/data.c` | Where a command's data is in the host's memory (🎓 PRPs). |
| `src/ftl.c` | The flash translation layer: which NAND page holds each page of the drive. |
| `src/buffer.c` | The SSD's buffer, and what the firmware keeps where in it. |
| `src/nvme.h` | As much of NVMe as the firmware speaks. |

It reaches the hardware through three drivers in socpuppet's Zephyr module (`python/socpuppet/zephyr_module/drivers/ssd/`): the NAND through Zephyr's own flash API, and the NVMe frontend and the DMA engine through small APIs of their own, in `<socpuppet/drivers/nvme_frontend.h>` and `<socpuppet/drivers/dma_engine.h>`.

💡 `python/socpuppet/ssd_firmware.py` is the same firmware as a Python script, section for section. It stands in for this one where there is no CPU, and the two are held to the same tests, `tests/python/test_ssd_firmware.py`.

Build it as any Zephyr application for the board, or with `firmware/build.sh`, which builds every image the tests boot:

```sh
west build -b socpuppet_ssd firmware/ssd -- \
    -DZEPHYR_EXTRA_MODULES="$(socpuppet zephyr-module)"
```

[docs/boot-your-firmware.md](../../docs/boot-your-firmware.md) says how to run it, and [docs/models/ssd-firmware.md](../../docs/models/ssd-firmware.md) what it does and leaves out.
