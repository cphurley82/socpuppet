#ifndef TESTS_CPP_CONTRACTS_LINK_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_LINK_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/models/memory.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/contracts/bus_driver.h"

// What every die-to-die link must do, whatever happens in between.
//
// A link is a pair of endpoints, one per die. Each endpoint has:
//   target, initiator            the die's side: traffic leaving it and
//                                entering it
//   peer_initiator, peer_target  the side facing the other endpoint
// Traffic flows both ways, because a device on one die may be the target of
// one transaction (a register access) and the initiator of the next (a DMA
// write into the other die's memory).
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, LinkContract,
//                                  ::testing::Types<MyEndpoint>);
// MyEndpoint must fit the link endpoint slot (see socpuppet/platform/slots.h).
template <socpuppet::LinkEndpointSlot Endpoint>
class LinkContract : public ::testing::Test {
 protected:
  LinkContract() {
    a_.peer_initiator.bind(b_.peer_target);
    b_.peer_initiator.bind(a_.peer_target);
    a_.initiator.bind(memory_on_a_.socket);
    b_.initiator.bind(memory_on_b_.socket);
  }

  // Runs `on_a` in a thread on die A and `on_b` in a thread on die B, each
  // wired to its own endpoint, to completion.
  void OnTheDies(
      std::function<void(BusDriver&)> on_a,
      std::function<void(BusDriver&)> on_b = [](BusDriver&) {}) {
    BusDriver driver_on_a{"driver_on_a", std::move(on_a)};
    BusDriver driver_on_b{"driver_on_b", std::move(on_b)};
    driver_on_a.socket.bind(a_.target);
    driver_on_b.socket.bind(b_.target);
    sc_core::sc_start();
  }

  Endpoint a_{"a"};
  Endpoint b_{"b"};
  socpuppet::Memory memory_on_a_{"memory_on_a", 0x100};
  socpuppet::Memory memory_on_b_{"memory_on_b", 0x100};
};

TYPED_TEST_SUITE_P(LinkContract);

TYPED_TEST_P(LinkContract, AWriteOnOneDieLandsInTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_on_b{};

  this->OnTheDies([&](BusDriver& on_a) { on_a.Write(0x10, written); });

  DebugRead(this->memory_on_b_, 0x10, seen_on_b);
  EXPECT_EQ(seen_on_b, written);
}

TYPED_TEST_P(LinkContract, AReadOnOneDieReturnsWhatIsInTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> read_on_a{};
  DebugWrite(this->memory_on_b_, 0x10, stored);

  this->OnTheDies([&](BusDriver& on_a) { on_a.Read(0x10, read_on_a); });

  EXPECT_EQ(read_on_a, stored);
}

TYPED_TEST_P(LinkContract, TrafficFlowsInBothDirectionsAtOnce) {
  const std::array<std::uint8_t, 4> from_a{0xAA, 0xAA, 0xAA, 0xAA};
  const std::array<std::uint8_t, 4> from_b{0xBB, 0xBB, 0xBB, 0xBB};
  std::array<std::uint8_t, 4> seen_on_a{};
  std::array<std::uint8_t, 4> seen_on_b{};

  this->OnTheDies([&](BusDriver& on_a) { on_a.Write(0x10, from_a); },
                  [&](BusDriver& on_b) { on_b.Write(0x10, from_b); });

  DebugRead(this->memory_on_a_, 0x10, seen_on_a);
  DebugRead(this->memory_on_b_, 0x10, seen_on_b);
  EXPECT_EQ(seen_on_a, from_b);
  EXPECT_EQ(seen_on_b, from_a);
}

TYPED_TEST_P(LinkContract, AnErrorResponseComesBackAcrossTheLink) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->OnTheDies([&](BusDriver& on_a) { response = on_a.Read(0x1000, data); });

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TYPED_TEST_P(LinkContract, ADebugReadOnOneDieSeesTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_by_debug{};
  DebugWrite(this->memory_on_b_, 0x10, stored);

  this->OnTheDies(
      [&](BusDriver& on_a) { on_a.DebugRead(0x10, seen_by_debug); });

  EXPECT_EQ(seen_by_debug, stored);
}

// A link may refuse direct memory access (a real link does: every access
// has to cross it). If it grants it, the grant has to be real.
TYPED_TEST_P(LinkContract,
             DirectMemoryAccessAcrossTheLinkIsEitherRefusedOrSeesLaterWrites) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_directly =
      written;  // what a refusal leaves untouched

  this->OnTheDies([&](BusDriver& on_a) {
    const DirectMemory direct = on_a.RequestDirectMemory(0x10);
    on_a.Write(0x10, written);
    if (direct.Granted()) direct.Read(seen_directly);
  });

  EXPECT_EQ(seen_directly, written);
}

REGISTER_TYPED_TEST_SUITE_P(
    LinkContract, AWriteOnOneDieLandsInTheMemoryOfTheOther,
    AReadOnOneDieReturnsWhatIsInTheMemoryOfTheOther,
    TrafficFlowsInBothDirectionsAtOnce, AnErrorResponseComesBackAcrossTheLink,
    ADebugReadOnOneDieSeesTheMemoryOfTheOther,
    DirectMemoryAccessAcrossTheLinkIsEitherRefusedOrSeesLaterWrites);

#endif  // TESTS_CPP_CONTRACTS_LINK_CONTRACT_H_
