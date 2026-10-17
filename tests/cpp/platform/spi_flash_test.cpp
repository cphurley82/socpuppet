#include "socpuppet/models/spi_flash.h"

#include <array>
#include <cstdint>
#include <functional>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "tests/cpp/support/bus_driver.h"

// What socpuppet relies on of its SPI flash: the window a boot ROM reads
// its image through, as if the flash were memory, and the way a platform
// fills it. The controller's SPI commands, which a driver would speak, are
// nobody's yet (M18).

namespace {

constexpr std::uint64_t kSize = 0x1000;
constexpr std::array<std::uint8_t, 4> kLoaded{0x11, 0x22, 0x33, 0x44};
constexpr std::uint64_t kLoadedAt = 0x10;
// The controller's status register, which says how much room it has for
// bytes to send, and so never reads as zero while it is idle. An erased
// flash does, and so does a read that nothing answers.
constexpr std::uint64_t kStatus = 0x04;

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

  socpuppet::SpiFlash flash{"flash", kSize};
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

// The borrowed chip is 256 MB whatever a platform asks for, and an access
// past that is not an error there but the end of the process.
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

TEST(AFlashsController, AnswersForItsRegistersOnItsOwnSocket) {
  std::uint32_t status = 0;

  Rig rig{[](BusDriver&) {},
          [&](BusDriver& registers) { status = registers.Read32(kStatus); }};

  EXPECT_NE(status, 0U);
}
