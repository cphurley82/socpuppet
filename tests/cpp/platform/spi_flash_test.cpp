#include "socpuppet/models/spi_flash.h"

#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/sifive_spi_driver.h"

// What socpuppet relies on of its SPI flash: the window a boot ROM reads
// its image through, as if the flash were memory, the way a platform fills
// it, and the chip a driver reaches through the controller.

namespace {

using ::testing::_;
using ::testing::ElementsAre;
using ::testing::Optional;

constexpr std::uint64_t kSize = 0x1000;
constexpr std::array<std::uint8_t, 4> kLoaded{0x11, 0x22, 0x33, 0x44};
constexpr std::uint64_t kLoadedAt = 0x10;

// A clock for a flash, and how long one tick of it is.
constexpr std::uint64_t kTenMegahertz = 10'000'000;
const sc_core::sc_time kTenMegahertzPeriod{1.0 / kTenMegahertz,
                                           sc_core::SC_SEC};

// A flash with a test's thread at its window, and a second at its
// controller's registers.
struct Rig {
  explicit Rig(
      const std::function<void(BusDriver& window)>& at_the_window,
      const std::function<void(BusDriver& registers)>& at_the_registers =
          [](BusDriver&) {})
      : window{"window", at_the_window},
        registers{"registers", at_the_registers} {
    window.socket.bind(flash.xip);
    registers.socket.bind(flash.socket);
    sc_core::sc_start();
  }

  socpuppet::SpiFlash flash{"flash", kSize, kTenMegahertz};
  BusDriver window;
  BusDriver registers;
};

// A chip on a flash's bus that notes when each byte reaches it.
struct TimingChip : socpuppet::SpiDevice {
  void Select() override {}
  std::uint8_t Transfer(std::uint8_t /*sent*/) override {
    arrivals.push_back(sc_core::sc_time_stamp());
    return 0;
  }
  void Deselect() override {}
  std::vector<sc_core::sc_time> arrivals;
};

// A flash with a clock and `device` at chip select 1, and a test's thread
// at its controller's registers.
struct ClockedRig {
  ClockedRig(std::uint64_t clock_hz, socpuppet::SpiDevice& device,
             const std::function<void(BusDriver&)>& at_the_registers)
      : flash{"flash", kSize, clock_hz},
        window{"window", [](BusDriver&) {}},
        registers{"registers", at_the_registers} {
    flash.Attach(1, device);
    window.socket.bind(flash.xip);
    registers.socket.bind(flash.socket);
    sc_core::sc_start();
  }

  socpuppet::SpiFlash flash;
  BusDriver window;
  BusDriver registers;
};

}  // namespace

TEST(WhatADebuggerWritesThroughAFlashsWindow, ABusReadThroughItSees) {
  std::array<std::uint8_t, 4> read{};

  Rig rig{[&](BusDriver& window) {
    window.DebugWrite(kLoadedAt, kLoaded);
    window.Read(kLoadedAt, read);
  }};

  EXPECT_EQ(read, kLoaded);
}

TEST(WhatADebuggerWritesThroughAFlashsWindow, ADebugReadThroughItSees) {
  std::array<std::uint8_t, 4> read{};
  unsigned transferred = 0;

  Rig rig{[&](BusDriver& window) {
    window.DebugWrite(kLoadedAt, kLoaded);
    transferred = window.DebugRead(kLoadedAt, read);
  }};

  EXPECT_EQ(transferred, read.size());
  EXPECT_EQ(read, kLoaded);
}

// A flash is not written by storing to it: that takes commands to its
// controller. The window is for reading.
TEST(ABusWriteThroughAFlashsWindow, IsRefusedAndChangesNothing) {
  const std::array<std::uint8_t, 4> written{0xde, 0xad, 0xbe, 0xef};
  std::array<std::uint8_t, 4> read{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  Rig rig{[&](BusDriver& window) {
    window.DebugWrite(kLoadedAt, kLoaded);
    response = window.Write(kLoadedAt, written);
    window.Read(kLoadedAt, read);
  }};

  EXPECT_EQ(response, tlm::TLM_COMMAND_ERROR_RESPONSE);
  EXPECT_EQ(read, kLoaded);
}

TEST(AnAccessThroughAFlashsWindowThatRunsPastItsSize, IsRefused) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status read = tlm::TLM_INCOMPLETE_RESPONSE;
  unsigned debug_read = 4;
  unsigned debug_written = 4;

  Rig rig{[&](BusDriver& window) {
    read = window.Read(kSize - 2, data);
    debug_read = window.DebugRead(kSize - 2, data);
    debug_written = window.DebugWrite(kSize - 2, data);
  }};

  EXPECT_EQ(read, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(debug_read, 0U);
  EXPECT_EQ(debug_written, 0U);
}

// Far past the flash is past any chip a platform could ask for, and must
// still be an error and not the end of the process, as it was with the
// chip socpuppet borrowed until M18.
TEST(AnAccessThroughAFlashsWindowFarPastItsSize, IsRefusedAndTheRunGoesOn) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status far_past = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status after = tlm::TLM_INCOMPLETE_RESPONSE;

  Rig rig{[&](BusDriver& window) {
    far_past = window.Read(0x1000'0000, data);
    after = window.Read(0, data);
  }};

  EXPECT_EQ(far_past, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(after, tlm::TLM_OK_RESPONSE);
}

// A boot ROM's reads are what booting from flash is there to show, a
// transaction each. A
// CPU that was granted direct memory access would make none.
TEST(AFlashsWindow, GrantsNoDirectMemoryAccess) {
  std::array<std::uint8_t, 4> data{};
  bool offered = true;
  bool granted = true;

  Rig rig{[&](BusDriver& window) {
    window.Read(0, data);
    offered = window.DirectMemoryWasOffered();
    granted = window.RequestDirectMemory(0).Granted();
  }};

  EXPECT_FALSE(offered);
  EXPECT_FALSE(granted);
}

// The chip on the controller's first chip select is this flash: its JEDEC
// id's capacity byte is 12, for 2 to the 12 bytes, kSize.
TEST(TheChipOnAFlashsFirstChipSelect, AnswersAJedecIdOfTheFlashsSize) {
  std::vector<std::optional<std::uint8_t>> id;

  Rig rig{[](BusDriver&) {},
          [&](BusDriver& registers) {
            const SifiveSpiDriver spi{registers};
            spi.Select(0);
            spi.Send(0x9F);
            for (int byte = 0; byte < 3; ++byte) id.push_back(spi.Send(0));
          }};

  EXPECT_THAT(id, ElementsAre(_, _, Optional(0x0C)));
}

// 🎓 SiFive's controller makes SPI's clock by dividing its own by
// 2 * (sckdiv + 1). Out of reset sckdiv is 0, so a byte's eight bits take
// sixteen of the flash's clocks.
TEST(BytesInABurstAtTheControllersResetDivisor,
     AreSixteenOfTheFlashsClocksApart) {
  TimingChip chip;

  ClockedRig rig{kTenMegahertz, chip, [](BusDriver& bus) {
                   const SifiveSpiDriver spi{bus};
                   spi.Select(1);
                   spi.SetTransmitMark(1);
                   spi.Format(/*transmit_only=*/true);
                   spi.Queue(0x11);
                   spi.Queue(0x22);
                   spi.WaitFor(SifiveSpiDriver::kTransmitWatermark);
                 }};

  ASSERT_EQ(chip.arrivals.size(), 2U);
  EXPECT_EQ(chip.arrivals[1] - chip.arrivals[0], 16 * kTenMegahertzPeriod);
}
