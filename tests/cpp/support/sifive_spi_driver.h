#ifndef TESTS_CPP_SUPPORT_SIFIVE_SPI_DRIVER_H_
#define TESTS_CPP_SUPPORT_SIFIVE_SPI_DRIVER_H_

#include <cstdint>
#include <optional>

#include <systemc>

#include "tests/cpp/support/bus_driver.h"

// A test's way to talk through an SPI controller with SiFive's registers,
// the way Zephyr's `spi_sifive` driver does: select a chip and hold its
// line low, send bytes a byte at a time and read each answer, then let the
// chip go. The registers are SiFive's, from the FE310's manual.
struct SifiveSpiDriver {
  // The registers, 32 bits each.
  static constexpr std::uint64_t kChipSelectId = 0x10;
  static constexpr std::uint64_t kChipSelectMode = 0x18;
  static constexpr std::uint64_t kTransmit = 0x48;
  static constexpr std::uint64_t kReceive = 0x4C;

  // The chip select modes: hold the selected chip's line low from the
  // first byte until the mode changes, or drive no line at all.
  static constexpr std::uint32_t kHold = 2;
  static constexpr std::uint32_t kOff = 3;
  // Set in the receive register when the receive FIFO had nothing in it.
  static constexpr std::uint32_t kReceiveEmpty = 1U << 31;

  // Selects the chip at `chip_select`: its id, then its line held low from
  // the first byte until the mode changes.
  void Select(unsigned chip_select) const {
    bus.Write32(kChipSelectId, chip_select);
    bus.Write32(kChipSelectMode, kHold);
  }

  // Lets the selected chip go, as a driver does at the end of a transfer:
  // no chip select line is driven.
  void LetGo() const { bus.Write32(kChipSelectMode, kOff); }

  // Sends one byte and returns what came back: the byte into the transmit
  // FIFO, then a look at the receive FIFO until a byte is there. Nothing,
  // if none comes within a millisecond, far longer than a byte takes at
  // any clock a test uses.
  std::optional<std::uint8_t> Send(std::uint8_t byte) const {
    bus.Write32(kTransmit, byte);
    const sc_core::sc_time give_up =
        sc_core::sc_time_stamp() + sc_core::sc_time{1, sc_core::SC_MS};
    while (sc_core::sc_time_stamp() < give_up) {
      const std::uint32_t received = bus.Read32(kReceive);
      if ((received & kReceiveEmpty) == 0) {
        return static_cast<std::uint8_t>(received);
      }
      // A driver's look takes time on a real bus; here it has to be made
      // to, or simulated time would never move on to the byte's arrival.
      bus.WaitFor(sc_core::sc_time{100, sc_core::SC_NS});
    }
    return std::nullopt;
  }

  BusDriver& bus;
};

#endif  // TESTS_CPP_SUPPORT_SIFIVE_SPI_DRIVER_H_
