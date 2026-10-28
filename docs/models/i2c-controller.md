# I2C controller

`sp.I2cController(devices=...)` · C++ `socpuppet::I2cController` · registry name `i2c_controller`

## What it stands for

The controller of an I2C bus. 🎓 I2C is a bus of two wires, a clock and a data line, that many small chips share: sensors, real-time clocks, the memory on a board that says what the board is. The controller starts a transfer and sends the address of the chip it wants, seven bits, and whether it will read or write; then bytes go one at a time, each acknowledged by whoever received it. A stop ends the transfer, and a start again before it begins another at once, as a read of a memory does after writing the address to read from.

This is the OpenCores I2C master core, which SiFive's chips have as their I2C block, and which Zephyr's `i2c_sifive` drives. The model is socpuppet's own, written from the core's specification.

## What it does

```python
from socpuppet.i2c import Ram

i2c = io.add("i2c", sp.I2cController(devices={0x51: Ram()}))
bus.map(i2c.cpu, base=0x100F_1000)
platform.connect(i2c.irq, aplic.source30)
```

| | |
|---|---|
| **Registers on the bus** (`cpu`) | A page: a byte to each 32-bit word, read or written as the byte or as the word. |
| **The interrupt** (`irq`) | Up when a command is done, while firmware has it enabled and has not cleared it. |

- **A command** is what firmware writes to `COMMAND`: a start, then a byte written or read, then a stop, any of them together, as the core's specification has it. A start sends the byte in `TRANSMIT`, which is the address and the direction.
- **A command takes time**: a byte and its acknowledgement are nine of the bus's clocks, and the bus's clock is the controller's, 50 MHz, over five times one more than the prescale. At 100 kHz a byte takes 90 µs. Meanwhile the status says a transfer is in progress, which is what Zephyr's driver waits on.
- **An address no device has** is not acknowledged: the status's `NO_ACK` says so. A read from no device reads 0xFF, the line pulled high.

### Python on the bus

🧵 Each device on the bus is a Python object with four methods (`socpuppet.i2c.I2cDevice`): `start(read)`, with its address, which returns whether it acknowledges; `write(byte)`, which does too; `read(last)`, which returns the byte, `last` saying the controller ends the read with it; and `stop()`. The controller calls them from its own process, never from the CPU's, so a device may take its time; time it takes is added to the transfer, as a real device holds the clock low until it is ready.

`socpuppet.i2c.Ram(size=...)` is a memory of the shape Zephyr's `i2c_ram` test wants, an FRAM's or an EEPROM's: a write sends two bytes of address, high one first, and then the bytes to put there; a read goes on from where the last write or read left off. The host takes devices as `host(i2c_devices={0x51: Ram()})`, and the shield `socpuppet_host_i2c_ram` puts one at 0x51.

### The registers

<!-- regs:i2c_controller start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x000` | `PRESCALE_LOW` | read, write | The low byte of the clock's prescale: the bus's clock is the controller's divided by five times one more than the prescale. At reset: `0x000000FF`. Bits 7 to 0 `VALUE`. |
| `0x004` | `PRESCALE_HIGH` | read, write | The high byte of the clock's prescale. At reset: `0x000000FF`. Bits 7 to 0 `VALUE`. |
| `0x008` | `CONTROL` | read, write | Switches the controller on, and its interrupt. Bit 6 `INTERRUPT_ENABLE`: The interrupt is raised when a command is done. Bit 7 `ENABLE`: The controller is on: commands are carried out. |
| `0x00C` | `TRANSMIT` | write | The next byte to send: an address, with the direction in bit 0 (1 is a read), or a byte of data. Bits 7 to 0 `VALUE`. |
| `0x00C` | `RECEIVE` | read | The last byte received. Bits 7 to 0 `VALUE`. |
| `0x010` | `COMMAND` | write | What the controller is to do next. Reads as status. Bit 0 `CLEAR_INTERRUPT`: Clears the interrupt. Bit 3 `NACK`: With a read: do not acknowledge the byte, which ends the read. Bit 4 `WRITE`: Send the byte in `TRANSMIT`. Bit 5 `READ`: Receive a byte into `RECEIVE`. Bit 6 `STOP`: After the byte, end the transfer. Bit 7 `START`: Before the byte, start a transfer, or start again. |
| `0x010` | `STATUS` | read | What the controller is doing, and what came of its last command. Bit 0 `INTERRUPT`: A command is done, and the interrupt not cleared. Bit 1 `TRANSFER_IN_PROGRESS`: A command is being carried out. Bit 5 `ARBITRATION_LOST`: Another controller won the bus. Never set: this one is alone on it. Bit 6 `BUSY`: Between a start and a stop. Bit 7 `NO_ACK`: The last byte sent was not acknowledged. |

<!-- regs:i2c_controller end -->

## What it leaves out

- **Other controllers on the bus.** This one is alone on it, so it never loses arbitration, and `ARBITRATION_LOST` is never set.
- **Ten-bit addresses**, and a device that answers a general call, address 0.
- **The bits on the wires.** A byte is carried out whole, at the end of its nine clocks; there is no start or stop condition to see on a line, and no device can hold the clock low part of the way through a byte, only between bytes, by taking its time.
- **A device that a start leaves for another** hears no stop, as on a real bus, where a repeated start addressed elsewhere is not one; it is not addressed again until a start names it.
- 🐧 **Linux.** Linux's driver for the core, `i2c-ocores`, is not in the stock kernel (`I2C_OCORES` is not set), so Linux's devicetree has no I2C controller.

## In a devicetree

Zephyr's has the controller as `sifive,i2c0`, with one cell to a device's address and none to a size, and the bus's speed, 100 kHz, I2C's standard mode, which Zephyr's driver sets at start. The driver takes the controller's own clock from socpuppet's `soc.h`, which gives SiFive's drivers the one their peripherals share (`PERIPHERAL_CLOCK_HZ` in `socpuppet.components`). On the host:

```dts
io_i2c: i2c@100f1000 {
	compatible = "sifive,i2c0";
	reg = <0x0 0x100f1000 0x0 0x1000>;
	#address-cells = <1>;
	#size-cells = <0>;
	clock-frequency = <100000>;
	interrupts-extended = <&io_aplic 30 1 4>;
};
```

## Under the hood

💡 The registers are written once, in `regs/i2c_controller.rdl`, and the logic is plain C++, `src/socpuppet/core/i2c_controller_logic.cpp`, with no simulation kernel: it carries out a command when told to, and says how many cycles it takes. The SystemC wrapper, `src/socpuppet/models/i2c_controller.h`, is a command device that waits those cycles first, from its own thread.

📮 Zephyr's `i2c_sifive` had two faults that silicon would show as well: it sent a device's address unshifted, and it started every message of a transfer again. Two patches put them right, and [upstream.md](../upstream.md) has both.

Zephyr's own `tests/drivers/i2c/i2c_ram` passes against Python's RAM, its RTIO cases too (`tests/python/test_zephyr_peripheral_samples.py`, and twister). `tests/cpp/unit/i2c_controller_logic_test.cpp` holds the logic, `tests/cpp/platform/i2c_controller_test.cpp` the wrapper's time and thread, and `tests/python/test_i2c_controller.py` a script driving it as firmware would.
