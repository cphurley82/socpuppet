#ifndef TESTS_CPP_SUPPORT_SIFIVE_SPI_DRIVER_H_
#define TESTS_CPP_SUPPORT_SIFIVE_SPI_DRIVER_H_

#include <cstdint>
#include <functional>
#include <optional>

#include <systemc>

#include "tests/cpp/support/bus_driver.h"

// A test's way to talk through an SPI controller with SiFive's registers,
// the way Zephyr's `spi_sifive` driver does: select a chip and hold its
// line low, send bytes a byte at a time and read each answer, then let the
// chip go. And the way Linux's `spi-sifive` does: fill the transmit FIFO,
// then wait for a watermark. The registers are SiFive's, from the FE310's
// manual.
struct SifiveSpiDriver {
  // The registers, 32 bits each.
  static constexpr std::uint64_t kChipSelectId = 0x10;
  static constexpr std::uint64_t kChipSelectMode = 0x18;
  static constexpr std::uint64_t kFormat = 0x40;
  static constexpr std::uint64_t kTransmit = 0x48;
  static constexpr std::uint64_t kReceive = 0x4C;
  static constexpr std::uint64_t kTransmitMark = 0x50;
  static constexpr std::uint64_t kInterruptPending = 0x74;

  // The chip select modes: hold the selected chip's line low from the
  // first byte until the mode changes, or drive no line at all.
  static constexpr std::uint32_t kHold = 2;
  static constexpr std::uint32_t kOff = 3;
  // Set in the receive register when the receive FIFO had nothing in it.
  static constexpr std::uint32_t kReceiveEmpty = 1U << 31;
  // The frame format: eight bits to a frame, in its length field, and
  // whether a transfer only transmits, so that nothing it gets back is kept.
  static constexpr std::uint32_t kEightBits = 8U << 16;
  static constexpr std::uint32_t kTransmitOnly = 1U << 3;
  // The transmit watermark, a bit of the interrupt registers: pending
  // while the transmit FIFO holds fewer bytes than its mark.
  static constexpr std::uint32_t kTransmitWatermark = 1U << 0;

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
  // if none comes.
  std::optional<std::uint8_t> Send(std::uint8_t byte) const {
    bus.Write32(kTransmit, byte);
    std::optional<std::uint8_t> answer;
    PollUntil([&] {
      const std::uint32_t received = bus.Read32(kReceive);
      if ((received & kReceiveEmpty) != 0) return false;
      answer = static_cast<std::uint8_t>(received);
      return true;
    });
    return answer;
  }

  // Sets the frame format as Linux's driver does before each transfer:
  // eight bits, and whether the transfer only transmits.
  void Format(bool transmit_only) const {
    bus.Write32(kFormat, kEightBits | (transmit_only ? kTransmitOnly : 0));
  }

  // Sets the transmit watermark's mark, as Linux's driver does once.
  void SetTransmitMark(std::uint32_t mark) const {
    bus.Write32(kTransmitMark, mark);
  }

  // Puts a byte in the transmit FIFO and goes on, as Linux's driver does
  // with as many as the FIFO holds before it waits.
  void Queue(std::uint8_t byte) const { bus.Write32(kTransmit, byte); }

  // Whether the interrupt bit `watermark` is pending now.
  bool Pending(std::uint32_t watermark) const {
    return (bus.Read32(kInterruptPending) & watermark) != 0;
  }

  // Waits until the interrupt bit `watermark` is pending, as Linux's driver
  // does when it polls. False if it never is.
  bool WaitFor(std::uint32_t watermark) const {
    return PollUntil([&] { return Pending(watermark); });
  }

  BusDriver& bus;

 private:
  // Looks until `done` says so, as a driver polls. False if it does not
  // within a millisecond, far longer than a FIFO's bytes take at any clock
  // a test uses.
  bool PollUntil(const std::function<bool()>& done) const {
    const sc_core::sc_time give_up =
        sc_core::sc_time_stamp() + sc_core::sc_time{1, sc_core::SC_MS};
    while (sc_core::sc_time_stamp() < give_up) {
      if (done()) return true;
      // A driver's look takes time on a real bus; here it has to be made
      // to, or simulated time would never move on to what it waits for.
      bus.WaitFor(sc_core::sc_time{100, sc_core::SC_NS});
    }
    return false;
  }
};

#endif  // TESTS_CPP_SUPPORT_SIFIVE_SPI_DRIVER_H_
