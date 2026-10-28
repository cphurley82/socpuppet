# GPIO

`sp.Gpio(pins=...)` · C++ `socpuppet::Gpio` · registry name `gpio`

## What it stands for

The pins of a chip that are for no one thing. 🎓 A GPIO pin, a general-purpose input or output, is one firmware decides the use of: it makes the pin an output and drives it high or low, to light an LED, say, or makes it an input and reads what is on it, a button's state. A pin can also interrupt when what is on it changes, so firmware hears of a button press without asking again and again.

This is the GPIO block of SiFive's FE310: 32 pins, which Zephyr's `gpio_sifive` driver uses through Zephyr's ordinary GPIO API.

## What it does

```python
gpio = io.add("gpio", sp.Gpio(pins=4))
bus.map(gpio.socket, base=0x100F_0000)
for pin in range(4):
    platform.connect(getattr(gpio, f"irq{pin}"), getattr(aplic, f"source{25 + pin}"))
platform.build()
gpio.on_change(lambda pin, level: print(pin, level))
```

| | |
|---|---|
| **Registers on the bus** (`socket`) | A page, 32 bits each, a bit for each pin. |
| **The interrupts** (`irq0` to `irq31`) | One for each pin, high while one of that pin's enabled events is pending. Connect one for each pin brought out. |

- **`pins`** is how many of the 32 a board brings out, from pin 0 up: 1 to 32. Firmware is told it has that many (`ngpios`).
- **A pin is an output** while its bit in `output_en` is set, and then drives its bit in `port`, the other way round where its bit in `out_xor` is set. Otherwise it drives nothing.
- **What is on a pin reads in `value`**: what is driven on it from outside, or with nothing driving it, its pull-up, which holds it high (`pue`), or low with none.
- **Four kinds of event** set a pin's bit pending: a rise and a fall as what is on an input changes, and a high and a low level for as long as it holds. So clearing a level that is still there leaves it pending, and its interrupt comes again. Each kind has a register of pending bits, cleared by writing a one, and one of enable bits.

### Python at the far end of the pins

🧵 Once the platform is built, Python is whatever the pins are wired to:

- **`gpio.level(pin)`** says what the GPIO drives on a pin: `True`, `False`, or `None` while the pin is not an output.
- **`gpio.drive(pin, level)`** drives a pin from outside: `True`, `False`, or `None` to let it go. Firmware reads it a delta cycle on, the next instant of the simulation at the same time.
- **`gpio.on_change(listener)`** has `listener(pin, level)` told of each change of what a pin drives, in order, a delta cycle after firmware made it. It is called from the GPIO's own process, never from the CPU's, so it may `drive` a pin in answer: a wire from one pin to another is `lambda pin, level: gpio.drive(1, level) if pin == 0 else None`.

⚠️ `level` is the GPIO's side of a pin only. What `drive` puts on a pin is for firmware to read, and `level` does not show it.

### The registers

| Offset | Register | |
|---|---|---|
| `0x00` | `value` | What is on each pin. |
| `0x04` | `input_en` | Kept and ignored: every pin that is not an output reads what is on it. |
| `0x08` | `output_en` | Which pins are outputs. |
| `0x0C` | `port` | What each output drives. |
| `0x10` | `pue` | Which pins have their pull-up on. |
| `0x14` | `ds` | Drive strength, kept and ignored. |
| `0x18`, `0x1C` | `rise_ie`, `rise_ip` | Rises: enabled, pending. |
| `0x20`, `0x24` | `fall_ie`, `fall_ip` | Falls. |
| `0x28`, `0x2C` | `high_ie`, `high_ip` | High levels. |
| `0x30`, `0x34` | `low_ie`, `low_ip` | Low levels. |
| `0x38`, `0x3C` | `iof_en`, `iof_sel` | A pin given to another block, which is not done here. |
| `0x40` | `out_xor` | Which outputs drive the other way round. |

## What it leaves out

- **A pin's electrical life.** A pin is high, low or driven by nothing. Two drivers on one pin, drive strength, and a pin with nothing on it floating to whatever it picked up last are not modelled: an undriven pin with no pull-up reads low.
- **`value` of an output.** On silicon `value` reads the pin itself, so it follows what an output drives. Here it holds what the pin last read as an input.
- **`input_en`.** A real pin whose input is disabled reads zero.
- **Other blocks on a pin** (`iof_en`), such as a UART's or an SPI's lines.
- **Timing.** What Python drives reads a delta cycle later, and a CPU running a quantum ahead of the clock sees it at the end of its quantum, up to 100 µs on. Zephyr's own GPIO test has a setting for wiring that is slow, `READ_DELAY`, which reads once more after a short sleep.

## In a devicetree

Zephyr's has the GPIO as `sifive,gpio0`, a `gpio-controller` with two cells to a pin, its pin and flags, `ngpios` from `pins`, and its interrupts the short way, `interrupt-parent` and `interrupts`, one for each pin brought out, in pin order. On the host:

```dts
io_gpio: gpio@100f0000 {
	compatible = "sifive,gpio0";
	reg = <0x0 0x100f0000 0x0 0x1000>;
	gpio-controller;
	#gpio-cells = <2>;
	ngpios = <4>;
	interrupt-parent = <&io_aplic>;
	interrupts = <25 1 4 26 1 4 27 1 4 28 1 4>;
};
```

🚧 Linux's tree has no GPIO yet. Linux's `gpio-sifive` puts an interrupt domain of its own on top of its parent's, which has not been checked on the host's APLIC.

## Under the hood

💡 The GPIO is SiFive's, borrowed from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals) by Minres, behind the adapter `src/socpuppet/models/gpio.cpp`, which is the far end of its pins. The borrowed model had the interrupt registers and nothing behind them, and its pull-ups did nothing: two patches add both, and [upstream.md](../upstream.md) has them, with what was read and left alone.

`tests/cpp/contracts/gpio_contract.h` holds the GPIO to what Zephyr's driver relies on, and `tests/python/test_gpio.py` holds Python's end of the pins.
