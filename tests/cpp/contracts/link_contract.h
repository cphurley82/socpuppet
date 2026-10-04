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
    a.peer_initiator.bind(b.peer_target);
    b.peer_initiator.bind(a.peer_target);
    a.initiator.bind(memory_on_a.socket);
    b.initiator.bind(memory_on_b.socket);
  }

  // Runs `on_a` in a thread on die A and `on_b` in a thread on die B, each
  // wired to its own endpoint, to completion.
  void on_the_dies(
      std::function<void(BusDriver&)> on_a,
      std::function<void(BusDriver&)> on_b = [](BusDriver&) {}) {
    BusDriver driver_on_a{"driver_on_a", std::move(on_a)};
    BusDriver driver_on_b{"driver_on_b", std::move(on_b)};
    driver_on_a.socket.bind(a.target);
    driver_on_b.socket.bind(b.target);
    sc_core::sc_start();
  }

  Endpoint a{"a"};
  Endpoint b{"b"};
  socpuppet::Memory memory_on_a{"memory_on_a", 0x100};
  socpuppet::Memory memory_on_b{"memory_on_b", 0x100};
};

TYPED_TEST_SUITE_P(LinkContract);

TYPED_TEST_P(LinkContract, AWriteOnOneDieLandsInTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_on_b{};

  this->on_the_dies([&](BusDriver& on_a) { on_a.write(0x10, written); });

  debug_read(this->memory_on_b, 0x10, seen_on_b);
  EXPECT_EQ(seen_on_b, written);
}

TYPED_TEST_P(LinkContract, AReadOnOneDieReturnsWhatIsInTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> read_on_a{};
  debug_write(this->memory_on_b, 0x10, stored);

  this->on_the_dies([&](BusDriver& on_a) { on_a.read(0x10, read_on_a); });

  EXPECT_EQ(read_on_a, stored);
}

TYPED_TEST_P(LinkContract, TrafficFlowsInBothDirectionsAtOnce) {
  const std::array<std::uint8_t, 4> from_a{0xAA, 0xAA, 0xAA, 0xAA};
  const std::array<std::uint8_t, 4> from_b{0xBB, 0xBB, 0xBB, 0xBB};
  std::array<std::uint8_t, 4> seen_on_a{};
  std::array<std::uint8_t, 4> seen_on_b{};

  this->on_the_dies([&](BusDriver& on_a) { on_a.write(0x10, from_a); },
                    [&](BusDriver& on_b) { on_b.write(0x10, from_b); });

  debug_read(this->memory_on_a, 0x10, seen_on_a);
  debug_read(this->memory_on_b, 0x10, seen_on_b);
  EXPECT_EQ(seen_on_a, from_b);
  EXPECT_EQ(seen_on_b, from_a);
}

TYPED_TEST_P(LinkContract, AnErrorResponseComesBackAcrossTheLink) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->on_the_dies(
      [&](BusDriver& on_a) { response = on_a.read(0x1000, data); });

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TYPED_TEST_P(LinkContract, ADebugReadOnOneDieSeesTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_by_debug{};
  debug_write(this->memory_on_b, 0x10, stored);

  this->on_the_dies(
      [&](BusDriver& on_a) { on_a.debug_read(0x10, seen_by_debug); });

  EXPECT_EQ(seen_by_debug, stored);
}

// A link may refuse direct memory access (a real link does: every access
// has to cross it). If it grants it, the grant has to be real.
TYPED_TEST_P(LinkContract,
             DirectMemoryAccessAcrossTheLinkIsEitherRefusedOrSeesLaterWrites) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_directly =
      written;  // what a refusal leaves untouched

  this->on_the_dies([&](BusDriver& on_a) {
    const DirectMemory direct = on_a.direct_memory(0x10);
    on_a.write(0x10, written);
    if (direct.granted()) direct.read(seen_directly);
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
