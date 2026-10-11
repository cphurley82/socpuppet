#ifndef TESTS_CPP_CONTRACTS_ROM_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_ROM_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

// What every read-only memory must do, whatever is behind it.
//
// A ROM's bytes are put there when the chip is made. Here that is a
// debugger's write, which is how a platform loads any memory, and it is
// taken only until the ROM's bus master first comes to it, with a
// transaction or a request for direct memory access: from then on the
// chip is made.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, RomContract,
//                                  ::testing::Types<MyRom>);
// MyRom must fit the memory slot (see socpuppet/platform/slots.h).
template <socpuppet::MemorySlot RomType>
class RomContract : public ::testing::Test {
 protected:
  static constexpr std::uint64_t kSize = 0x100;
  static constexpr std::array<std::uint8_t, 4> kLoaded{0x11, 0x22, 0x33, 0x44};
  static constexpr std::uint64_t kLoadedAt = 0x10;

  // Puts kLoaded into the ROM the way a platform does, before anything
  // runs.
  void Load() { DebugWrite(rom_, kLoadedAt, kLoaded); }

  // Runs `body` in a simulation thread wired to the ROM, to completion.
  void OnTheBus(std::function<void(BusDriver&)> body) {
    BusDriver driver{"driver", std::move(body)};
    driver.socket.bind(rom_.socket);
    sc_core::sc_start();
  }

  RomType rom_{"rom", kSize};
};

TYPED_TEST_SUITE_P(RomContract);

TYPED_TEST_P(RomContract, ABusReadSeesWhatWasLoaded) {
  std::array<std::uint8_t, 4> read{};
  this->Load();

  this->OnTheBus([&](BusDriver& bus) { bus.Read(this->kLoadedAt, read); });

  EXPECT_EQ(read, this->kLoaded);
}

TYPED_TEST_P(RomContract, ABusWriteIsRefusedAndChangesNothing) {
  const std::array<std::uint8_t, 4> written{0xde, 0xad, 0xbe, 0xef};
  std::array<std::uint8_t, 4> read{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  this->Load();

  this->OnTheBus([&](BusDriver& bus) {
    response = bus.Write(this->kLoadedAt, written);
    bus.Read(this->kLoadedAt, read);
  });

  EXPECT_EQ(response, tlm::TLM_COMMAND_ERROR_RESPONSE);
  EXPECT_EQ(read, this->kLoaded);
}

TYPED_TEST_P(RomContract, ABusReadThatRunsPastTheEndGetsAnAddressError) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->OnTheBus(
      [&](BusDriver& bus) { response = bus.Read(this->kSize - 2, data); });

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TYPED_TEST_P(RomContract, ACompletedReadOffersDirectMemoryAccess) {
  std::array<std::uint8_t, 4> data{};
  bool offered = false;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Read(0x10, data);
    offered = bus.DirectMemoryWasOffered();
  });

  EXPECT_TRUE(offered) << "no DMI-allowed hint on the read";
}

TYPED_TEST_P(RomContract, DirectMemoryAccessSeesWhatWasLoaded) {
  std::array<std::uint8_t, 4> seen_directly{};
  bool granted = false;
  this->Load();

  this->OnTheBus([&](BusDriver& bus) {
    const DirectMemory direct = bus.RequestDirectMemory(this->kLoadedAt);
    granted = direct.Granted();
    if (granted) direct.Read(seen_directly);
  });

  ASSERT_TRUE(granted) << "the ROM did not grant direct memory access";
  EXPECT_EQ(seen_directly, this->kLoaded);
}

TYPED_TEST_P(RomContract,
             DirectMemoryAccessIsForReadingOnlyAndStopsAtTheEndOfTheRom) {
  DirectMemory direct;

  this->OnTheBus(
      [&](BusDriver& bus) { direct = bus.RequestDirectMemory(0x10); });

  ASSERT_TRUE(direct.Granted()) << "the ROM did not grant direct memory access";
  EXPECT_TRUE(direct.ReadAllowed());
  EXPECT_FALSE(direct.WriteAllowed());
  EXPECT_LE(direct.BytesToEnd(), this->kSize - 0x10);
}

TYPED_TEST_P(RomContract, ADebugReadSeesWhatWasLoaded) {
  std::array<std::uint8_t, 4> seen_by_debug{};
  unsigned transferred = 0;
  this->Load();

  this->OnTheBus([&](BusDriver& bus) {
    transferred = bus.DebugRead(this->kLoadedAt, seen_by_debug);
  });

  EXPECT_EQ(transferred, seen_by_debug.size());
  EXPECT_EQ(seen_by_debug, this->kLoaded);
}

TYPED_TEST_P(RomContract, ADebugAccessThatRunsPastTheEndTransfersNothing) {
  std::array<std::uint8_t, 4> data{};
  unsigned written = 4;
  unsigned read = 4;

  this->OnTheBus([&](BusDriver& bus) {
    written = bus.DebugWrite(this->kSize - 2, data);
    read = bus.DebugRead(this->kSize - 2, data);
  });

  EXPECT_EQ(written, 0U);
  EXPECT_EQ(read, 0U);
}

// Loading is not one write: an ELF file is a segment at a time, and a
// script may look at what it has loaded so far.
TYPED_TEST_P(RomContract, ADebugWriteAfterADebugReadIsTaken) {
  const std::array<std::uint8_t, 4> more{0x55, 0x66, 0x77, 0x88};
  std::array<std::uint8_t, 4> read{};
  this->Load();

  this->OnTheBus([&](BusDriver& bus) {
    bus.DebugRead(this->kLoadedAt, read);
    bus.DebugWrite(0x20, more);
    bus.Read(0x20, read);
  });

  EXPECT_EQ(read, more);
}

TYPED_TEST_P(RomContract, ADebugWriteAfterABusReadIsRefusedAndChangesNothing) {
  const std::array<std::uint8_t, 4> patch{0xde, 0xad, 0xbe, 0xef};
  std::array<std::uint8_t, 4> read{};
  unsigned transferred = 4;
  this->Load();

  this->OnTheBus([&](BusDriver& bus) {
    bus.Read(0x0, read);
    transferred = bus.DebugWrite(this->kLoadedAt, patch);
    bus.DebugRead(this->kLoadedAt, read);
  });

  EXPECT_EQ(transferred, 0U);
  EXPECT_EQ(read, this->kLoaded);
}

// Any transaction is the bus master come to the ROM, one that is refused
// as much as one that is answered.
TYPED_TEST_P(RomContract, ADebugWriteAfterABusWriteIsRefusedAndChangesNothing) {
  const std::array<std::uint8_t, 4> patch{0xde, 0xad, 0xbe, 0xef};
  std::array<std::uint8_t, 4> read{};
  unsigned transferred = 4;
  this->Load();

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write(0x0, patch);
    transferred = bus.DebugWrite(this->kLoadedAt, patch);
    bus.DebugRead(this->kLoadedAt, read);
  });

  EXPECT_EQ(transferred, 0U);
  EXPECT_EQ(read, this->kLoaded);
}

// A CPU that reads through direct memory access makes no bus read at all,
// and is no less the ROM's reader for that.
TYPED_TEST_P(
    RomContract,
    ADebugWriteAfterDirectMemoryWasAskedForIsRefusedAndChangesNothing) {
  const std::array<std::uint8_t, 4> patch{0xde, 0xad, 0xbe, 0xef};
  std::array<std::uint8_t, 4> read{};
  unsigned transferred = 4;
  this->Load();

  this->OnTheBus([&](BusDriver& bus) {
    bus.RequestDirectMemory(0x0);
    transferred = bus.DebugWrite(this->kLoadedAt, patch);
    bus.DebugRead(this->kLoadedAt, read);
  });

  EXPECT_EQ(transferred, 0U);
  EXPECT_EQ(read, this->kLoaded);
}

REGISTER_TYPED_TEST_SUITE_P(
    RomContract, ABusReadSeesWhatWasLoaded, ABusWriteIsRefusedAndChangesNothing,
    ABusReadThatRunsPastTheEndGetsAnAddressError,
    ACompletedReadOffersDirectMemoryAccess, DirectMemoryAccessSeesWhatWasLoaded,
    DirectMemoryAccessIsForReadingOnlyAndStopsAtTheEndOfTheRom,
    ADebugReadSeesWhatWasLoaded, ADebugAccessThatRunsPastTheEndTransfersNothing,
    ADebugWriteAfterADebugReadIsTaken,
    ADebugWriteAfterABusReadIsRefusedAndChangesNothing,
    ADebugWriteAfterABusWriteIsRefusedAndChangesNothing,
    ADebugWriteAfterDirectMemoryWasAskedForIsRefusedAndChangesNothing);

#endif  // TESTS_CPP_CONTRACTS_ROM_CONTRACT_H_
