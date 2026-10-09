# Zephyr's flash test, on the SSD's NAND 🧦

Zephyr has a test that any driver of its flash class should pass: `tests/drivers/flash/common` in Zephyr's tree. This directory builds that test, as it is, for the board `socpuppet_ssd`, where the flash is the SSD's NAND and the driver is socpuppet's own, for the [flash controller](../../docs/models/flash-controller.md).

💡 It is here because of the rule socpuppet has for anything borrowed: hold it to a contract. The driver borrows Zephyr's flash interface, so the contract is Zephyr's test of that interface, and nearly all of it was written there.

| File | What is in it |
|---|---|
| `CMakeLists.txt` | Builds Zephyr's `src/main.c`, from Zephyr's tree, and `src/nand.c`. |
| `src/nand.c` | Four cases of socpuppet's own, for what only a NAND does: a write of more than one page, and the writes, erases and reads the driver refuses. |
| `Kconfig` | Zephyr's, for the test's own options. |
| `prj.conf` | What Zephyr's test asks for, and three settings for a NAND: the test writes whole pages, from bigger buffers, and is told the size to expect. |
| `boards/socpuppet_ssd.overlay` | A partition called `storage_partition`, which is where the test looks for somewhere to write. |

`firmware/build.sh` builds it, and `tests/python/test_zephyr_flash_driver.py` boots it and reads the verdict off the console.
