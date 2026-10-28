# I2C controller

`sp.I2cController()` · C++ `socpuppet::I2cController` · registry name `i2c_controller`

## What it stands for

The controller of an I2C bus. 🎓 I2C is a bus of two wires, a clock and a data line, that many small chips share: sensors, real-time clocks, the memory on a board that says what the board is. The controller starts a transfer, sends the address of the chip it wants and whether it will read or write, and then sends or receives bytes one at a time; each byte is acknowledged by whoever received it.

This is the OpenCores I2C master core, which SiFive's chips have as their I2C block, and which Zephyr's `i2c_sifive` and Linux's `i2c-ocores` drive.

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
