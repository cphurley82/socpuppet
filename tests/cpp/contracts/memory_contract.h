#ifndef TESTS_CPP_CONTRACTS_MEMORY_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_MEMORY_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/platform/slots.h"
#include "tests/cpp/contracts/bus_driver.h"

// What every memory implementation must do, whatever is behind it.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, MemoryContract,
//                                  ::testing::Types<MyMemory>);
// MyMemory must fit the memory slot (see socpuppet/platform/slots.h).
template <socpuppet::MemorySlot MemoryType>
class MemoryContract : public ::testing::Test {
 protected:
  static constexpr std::uint64_t kSize = 0x100;

  // Runs `body` in a simulation thread wired to the memory, to completion.
  void OnTheBus(std::function<void(BusDriver&)> body) {
    BusDriver driver{"driver", std::move(body)};
    driver.socket.bind(memory_.socket);
    sc_core::sc_start();
  }

  MemoryType memory_{"memory", kSize};
};

TYPED_TEST_SUITE_P(MemoryContract);

TYPED_TEST_P(MemoryContract, AReadAfterAWriteReturnsTheWrittenBytes) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> read{};

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write(0x10, written);
    bus.Read(0x10, read);
  });

  EXPECT_EQ(read, written);
}

TYPED_TEST_P(MemoryContract,
             AnAccessThatRunsPastTheEndGetsAnAddressErrorResponse) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status write_response = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status read_response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->OnTheBus([&](BusDriver& bus) {
    write_response = bus.Write(this->kSize - 2, data);
    read_response = bus.Read(this->kSize - 2, data);
  });

  EXPECT_EQ(write_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(read_response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TYPED_TEST_P(MemoryContract, ACompletedAccessOffersDirectMemoryAccess) {
  std::array<std::uint8_t, 4> data{};
  bool offered_after_write = false;
  bool offered_after_read = false;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write(0x10, data);
    offered_after_write = bus.DirectMemoryWasOffered();
    bus.Read(0x10, data);
    offered_after_read = bus.DirectMemoryWasOffered();
  });

  EXPECT_TRUE(offered_after_write) << "no DMI-allowed hint on the write";
  EXPECT_TRUE(offered_after_read) << "no DMI-allowed hint on the read";
}

TYPED_TEST_P(MemoryContract, DirectMemoryAccessSeesLaterWrites) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_directly{};
  bool granted = false;

  this->OnTheBus([&](BusDriver& bus) {
    const DirectMemory direct = bus.RequestDirectMemory(0x10);
    granted = direct.Granted();
    if (!granted) return;
    bus.Write(0x10, written);
    direct.Read(seen_directly);
  });

  ASSERT_TRUE(granted) << "the memory did not grant direct memory access";
  EXPECT_EQ(seen_directly, written);
}

TYPED_TEST_P(MemoryContract,
             DirectMemoryAccessIsReadWriteAndStopsAtTheEndOfTheMemory) {
  DirectMemory direct;

  this->OnTheBus(
      [&](BusDriver& bus) { direct = bus.RequestDirectMemory(0x10); });

  ASSERT_TRUE(direct.Granted())
      << "the memory did not grant direct memory access";
  EXPECT_TRUE(direct.ReadWriteAllowed());
  EXPECT_LE(direct.BytesToEnd(), this->kSize - 0x10);
}

TYPED_TEST_P(MemoryContract, ADebugReadSeesWhatTheBusWrote) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_by_debug{};

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write(0x10, written);
    bus.DebugRead(0x10, seen_by_debug);
  });

  EXPECT_EQ(seen_by_debug, written);
}

TYPED_TEST_P(MemoryContract, ABusReadSeesWhatDebugWrote) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_by_bus{};

  this->OnTheBus([&](BusDriver& bus) {
    bus.DebugWrite(0x10, written);
    bus.Read(0x10, seen_by_bus);
  });

  EXPECT_EQ(seen_by_bus, written);
}

REGISTER_TYPED_TEST_SUITE_P(
    MemoryContract, AReadAfterAWriteReturnsTheWrittenBytes,
    AnAccessThatRunsPastTheEndGetsAnAddressErrorResponse,
    ACompletedAccessOffersDirectMemoryAccess, DirectMemoryAccessSeesLaterWrites,
    DirectMemoryAccessIsReadWriteAndStopsAtTheEndOfTheMemory,
    ADebugReadSeesWhatTheBusWrote, ABusReadSeesWhatDebugWrote);

#endif  // TESTS_CPP_CONTRACTS_MEMORY_CONTRACT_H_
