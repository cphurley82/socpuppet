# Tests of the module's drivers 🧦

Each directory under `drivers/` is a small Zephyr application that tests one driver or device of this module from inside Zephyr, one call at a time, on the board its hardware is on. They are written with ztest, Zephyr's test framework, and run by twister, Zephyr's test runner, with socpuppet as the emulator:

```sh
west twister -T $(socpuppet zephyr-module)/tests   # with a Zephyr workspace of your own
firmware/twister.sh -T python/socpuppet/zephyr_module/tests   # in a checkout of socpuppet
```

🎓 A driver's test needs the driver's hardware to do something, and some hardware only does something when asked from outside. So a `testcase.yaml` here may name a shield, and with it `socpuppet run` puts 🎭 a stand-in on the other side. `socpuppet_ssd_host` is a host in front of the SSD that says a host's first words to a drive: it enables it, asks for its queues and how big it is, and writes one block. ⚠️ That host waits one second of simulated time to be told the drive is ready, so a suite built with the shield says so, or is done, within it. [docs/twister.md](https://github.com/cphurley82/socpuppet/blob/main/docs/twister.md) in socpuppet has the rest.
