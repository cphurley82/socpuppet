#ifndef TESTS_CPP_CONTRACTS_LINK_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_LINK_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/test_components.h"

// The two dies a link joins. "a" is the die that brings the link up, the
// way the IO die's manager does; "b" waits for it.
constexpr const char* kDieA = "a";
constexpr const char* kDieB = "b";

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
//   a.driver ─▶ a.bus ─▶ the endpoint on a ═══▶ the endpoint on b ─▶ b.memory
//   b.driver ─▶ b.bus ─▶ the endpoint on b ═══▶ the endpoint on a ─▶ a.memory
//
// Each die's window onto the other starts at zero, so an address on one die
// is the same address in the other die's memory.
//
// To hold an implementation to this contract, write a rig for it and
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, LinkContract,
//                                  ::testing::Types<MyRig>);
// A rig says how to put the link into a platform, and how to bring it up:
//   static void Register(socpuppet::Registry&);   adds whatever it is made
//       of that the built-in components do not already have
//   static void Add(socpuppet::Platform&);   adds the two endpoints, bound
//       to each other, under any names that do not collide with the
//       fixture's own "<die>.driver", "<die>.bus" and "<die>.memory"
//   static std::string Target(const char* die);   the port traffic leaving
//       that die is given to (a bus target)
//   static std::string Initiator(const char* die);   the port traffic
//       arriving on it comes out of (a bus source)
//   static void BringUp(BusDriver&);   trains the link, from die a, and
//       returns once it is up. A link that is always up does nothing here.
//   static void WaitUntilUp(BusDriver&);   the same wait, on die b, which
//       starts no training of its own
//
// The endpoints must fit the link endpoint slot (socpuppet/platform/slots.h).
template <typename Rig>
class LinkContract : public ::testing::Test {
 public:
  // How far each die's window onto the other reaches. Bigger than either
  // memory, so that an address past the end of a memory is the memory's to
  // refuse and not the bus's.
  static constexpr std::uint64_t kWindowSize = 0x1'0000;
  static constexpr std::uint64_t kMemorySize = 0x100;

 protected:
  LinkContract() {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    Rig::Register(registry);
    AddBusDriver(registry, DriverOf(kDieA),
                 [this](BusDriver& bus) { RunOnDieA(bus); });
    AddBusDriver(registry, DriverOf(kDieB),
                 [this](BusDriver& bus) { RunOnDieB(bus); });
    platform_ = std::make_unique<socpuppet::Platform>(std::move(registry));
    Rig::Add(*platform_);
    AddDie(kDieA);
    AddDie(kDieB);
    platform_->Elaborate();
  }

  // Runs `on_a` in a thread on die A and `on_b` in a thread on die B, each
  // wired to its own endpoint, to completion. The link is up before either
  // starts.
  void OnTheDies(
      std::function<void(BusDriver&)> on_a,
      std::function<void(BusDriver&)> on_b = [](BusDriver&) {}) {
    on_a_ = std::move(on_a);
    on_b_ = std::move(on_b);
    platform_->Run();
  }

  // What a die's own memory holds, seen from its endpoint and so without
  // crossing the link, the way a debugger attached to that die sees it.
  void DebugRead(const char* die, std::uint64_t address,
                 std::span<std::uint8_t> data) {
    platform_->DebugRead(Rig::Initiator(die), address,
                         std::as_writable_bytes(data));
  }
  void DebugWrite(const char* die, std::uint64_t address,
                  std::span<const std::uint8_t> data) {
    platform_->DebugWrite(Rig::Initiator(die), address, std::as_bytes(data));
  }

  std::unique_ptr<socpuppet::Platform> platform_;

 private:
  static std::string DriverOf(const char* die) {
    return std::string("driver_on_") + die;
  }

  void AddDie(const char* die) {
    const std::string group{die};
    platform_->Add(group + ".driver", DriverOf(die));
    platform_->Add(
        group + ".bus", "router",
        {{"outputs", 1}, {"out0.base", 0}, {"out0.size", kWindowSize}});
    platform_->Add(group + ".memory", "memory", {{"size", kMemorySize}});
    platform_->Bind(group + ".driver.socket", group + ".bus.target");
    platform_->Bind(group + ".bus.out0", Rig::Target(die));
    platform_->Bind(Rig::Initiator(die), group + ".memory.socket");
  }

  void RunOnDieA(BusDriver& bus) {
    Rig::BringUp(bus);
    on_a_(bus);
    Finished();
  }
  void RunOnDieB(BusDriver& bus) {
    Rig::WaitUntilUp(bus);
    on_b_(bus);
    Finished();
  }
  // The run ends when both dies have done what they were given. Waiting for
  // the simulation to run out of work would wait for the link's own
  // processes too, and a link that keeps a timer running has none.
  void Finished() {
    if (--still_running_ == 0) sc_core::sc_pause();
  }

  std::function<void(BusDriver&)> on_a_ = [](BusDriver&) {};
  std::function<void(BusDriver&)> on_b_ = [](BusDriver&) {};
  int still_running_ = 2;
};

TYPED_TEST_SUITE_P(LinkContract);

TYPED_TEST_P(LinkContract, AWriteOnOneDieLandsInTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_on_b{};

  this->OnTheDies([&](BusDriver& on_a) { on_a.Write(0x10, written); });

  this->DebugRead(kDieB, 0x10, seen_on_b);
  EXPECT_EQ(seen_on_b, written);
}

TYPED_TEST_P(LinkContract, AReadOnOneDieReturnsWhatIsInTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> read_on_a{};
  this->DebugWrite(kDieB, 0x10, stored);

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

  this->DebugRead(kDieA, 0x10, seen_on_a);
  this->DebugRead(kDieB, 0x10, seen_on_b);
  EXPECT_EQ(seen_on_a, from_b);
  EXPECT_EQ(seen_on_b, from_a);
}

TYPED_TEST_P(LinkContract, AnErrorResponseComesBackAcrossTheLink) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  // Inside the die's window onto the other, so the bus carries it across,
  // and past the end of the far memory, which is what refuses it.
  const std::uint64_t past_the_far_memory = TestFixture::kMemorySize;

  this->OnTheDies([&](BusDriver& on_a) {
    response = on_a.Read(past_the_far_memory, data);
  });

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TYPED_TEST_P(LinkContract, ADebugReadOnOneDieSeesTheMemoryOfTheOther) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen_by_debug{};
  this->DebugWrite(kDieB, 0x10, stored);

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
