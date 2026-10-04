#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "bus_driver.h"

// What every memory implementation must do, whatever is behind it.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, MemoryContract, ::testing::Types<MyMemory>);
// MyMemory must be constructible from (name, size in bytes) and expose a TLM
// target socket named `socket`.
template <typename MemoryType>
class MemoryContract : public ::testing::Test {
 protected:
  static constexpr std::uint64_t size = 0x100;

  // Runs `body` in a simulation thread wired to the memory, to completion.
  void on_the_bus(std::function<void(BusDriver&)> body) {
    BusDriver driver{"driver", std::move(body)};
    driver.socket.bind(memory.socket);
    sc_core::sc_start();
  }

  MemoryType memory{"memory", size};
};

TYPED_TEST_SUITE_P(MemoryContract);

TYPED_TEST_P(MemoryContract, AReadAfterAWriteReturnsTheWrittenBytes) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> read{};

  this->on_the_bus([&](BusDriver& bus) {
    bus.write(0x10, written);
    bus.read(0x10, read);
  });

  EXPECT_EQ(read, written);
}

TYPED_TEST_P(MemoryContract, AnAccessThatRunsPastTheEndGetsAnAddressErrorResponse) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status write_response = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status read_response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->on_the_bus([&](BusDriver& bus) {
    write_response = bus.write(this->size - 2, data);
    read_response = bus.read(this->size - 2, data);
  });

  EXPECT_EQ(write_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(read_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TYPED_TEST_P(MemoryContract, DirectMemoryAccessSeesLaterWrites) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_directly{};
  bool granted = false;

  this->on_the_bus([&](BusDriver& bus) {
    const DirectMemory direct = bus.direct_memory(0x10);
    granted = direct.granted();
    if (!granted) return;
    bus.write(0x10, written);
    direct.read(seen_directly);
  });

  ASSERT_TRUE(granted) << "the memory did not grant direct memory access";
  EXPECT_EQ(seen_directly, written);
}

TYPED_TEST_P(MemoryContract, DirectMemoryAccessIsReadWriteAndStopsAtTheEndOfTheMemory) {
  DirectMemory direct;

  this->on_the_bus([&](BusDriver& bus) { direct = bus.direct_memory(0x10); });

  ASSERT_TRUE(direct.granted()) << "the memory did not grant direct memory access";
  EXPECT_TRUE(direct.read_write_allowed());
  EXPECT_LE(direct.bytes_to_end(), this->size - 0x10);
}

TYPED_TEST_P(MemoryContract, ADebugReadSeesWhatTheBusWrote) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_by_debug{};

  this->on_the_bus([&](BusDriver& bus) {
    bus.write(0x10, written);
    bus.debug_read(0x10, seen_by_debug);
  });

  EXPECT_EQ(seen_by_debug, written);
}

TYPED_TEST_P(MemoryContract, ABusReadSeesWhatDebugWrote) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_by_bus{};

  this->on_the_bus([&](BusDriver& bus) {
    bus.debug_write(0x10, written);
    bus.read(0x10, seen_by_bus);
  });

  EXPECT_EQ(seen_by_bus, written);
}

REGISTER_TYPED_TEST_SUITE_P(MemoryContract, AReadAfterAWriteReturnsTheWrittenBytes,
                            AnAccessThatRunsPastTheEndGetsAnAddressErrorResponse,
                            DirectMemoryAccessSeesLaterWrites,
                            DirectMemoryAccessIsReadWriteAndStopsAtTheEndOfTheMemory,
                            ADebugReadSeesWhatTheBusWrote, ABusReadSeesWhatDebugWrote);
