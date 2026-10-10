#include "socpuppet/models/d2d_link.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/ucie_link_registers.h"
#include "socpuppet/core/ucie_sideband.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/recording_target.h"
#include "tests/cpp/support/test_components.h"
#include "tests/cpp/support/ucie_link_driving.h"

namespace socpuppet {
namespace {

using Registers = UcieLinkRegisters;

// Where each die's bus has its own link registers, and where its window
// onto the other die starts. The window is an identity map, as the board
// has it: an address on one die is the same address on the other.
constexpr std::uint64_t kSideband = 0x1000'0000;
constexpr std::uint64_t kWindowSize = 0x1'0000;

// The link under test: 20 ns to cross and 16 bytes of it in a nanosecond,
// which the timing below is worked out from. Training is given a tenth of
// a millisecond, because no test here is about how long it takes.
constexpr std::uint64_t kLatencyNs = 20;
constexpr std::uint64_t kBytesPerNs = 16;
constexpr std::uint64_t kTrainingNs = 100'000;

// What each die has for the other to reach, in its own addresses: a small
// memory, and a target that writes down what arrives and when.
constexpr std::uint64_t kMemoryOnTheOtherDie = 0;
constexpr std::uint64_t kEarsOnTheOtherDie = 0x1000;
constexpr std::uint64_t kBlockSize = 0x100;

// Two dies joined by a link, each with a bus master in its firmware's
// place behind a router, a target on the far side of the link to catch
// what crosses, and a test's eyes on the reset and interrupt lines.
//
//   <die>.driver ─▶ <die>.bus ─┬─▶ <die>.link.target ══▶ the other die
//                              └─▶ <die>.link.sideband (its registers)
//   <die>.link.initiator ─▶ <die>.in ─┬─▶ <die>.memory
//                                     └─▶ <die>.arrivals
//   <die>.link.reset ─▶ <die>.reset_watcher
//   <die>.link.irq ─▶ <die>.irq_watcher
class TwoDiesOnALink {
 public:
  TwoDiesOnALink() {
    Registry registry = BuiltinComponents();
    AddBusDriver(registry, "driver_on_a",
                 [this](BusDriver& bus) { on_a_(bus); });
    AddBusDriver(registry, "driver_on_b",
                 [this](BusDriver& bus) { on_b_(bus); });
    AddRecordingTarget(registry, "arrivals_on_a", arrived_on_a_,
                       sc_core::SC_ZERO_TIME);
    AddRecordingTarget(registry, "arrivals_on_b", arrived_on_b_,
                       sc_core::SC_ZERO_TIME);
    AddLineWatcher(registry, "line_watcher");
    platform_ = std::make_unique<Platform>(std::move(registry));
    AddDie("a");
    AddDie("b");
    platform_->Bind("a.link.peer_initiator", "b.link.peer_target");
    platform_->Bind("b.link.peer_initiator", "a.link.peer_target");
    platform_->Bind("a.link.sideband_peer_initiator",
                    "b.link.sideband_peer_target");
    platform_->Bind("b.link.sideband_peer_initiator",
                    "a.link.sideband_peer_target");
    platform_->Elaborate();
  }

  // Runs `on_a` on die A and `on_b` on die B, each in its own thread, to
  // completion.
  void OnTheDies(
      std::function<void(BusDriver&)> on_a,
      std::function<void(BusDriver&)> on_b = [](BusDriver&) {}) {
    on_a_ = std::move(on_a);
    on_b_ = std::move(on_b);
    platform_->Run();
  }

  LineWatcher& ResetOn(const std::string& die) {
    return platform_->ModuleAt<LineWatcher>(die + ".reset_watcher");
  }
  LineWatcher& IrqOn(const std::string& die) {
    return platform_->ModuleAt<LineWatcher>(die + ".irq_watcher");
  }
  const std::vector<RecordedAccess>& ArrivedOnB() const {
    return arrived_on_b_;
  }

  // What a die's own memory holds, put there or read back without
  // crossing the link.
  void DebugWriteOn(const std::string& die, std::uint64_t address,
                    std::span<const std::uint8_t> data) {
    platform_->DebugWrite(die + ".link.initiator", address,
                          std::as_bytes(data));
  }

 private:
  void AddDie(const std::string& die) {
    platform_->Add(die + ".driver", "driver_on_" + die);
    platform_->Add(die + ".bus", "router",
                   {{"outputs", 2},
                    {"out0.base", 0},
                    {"out0.size", kWindowSize},
                    {"out1.base", kSideband},
                    {"out1.size", Registers::kSize}});
    platform_->Add(die + ".link", "d2d_link_endpoint",
                   {{"latency_ns", kLatencyNs},
                    {"bytes_per_ns", kBytesPerNs},
                    {"training_ns", kTrainingNs}});
    platform_->Add(die + ".arrivals", "arrivals_on_" + die);
    platform_->Add(die + ".reset_watcher", "line_watcher");
    platform_->Add(die + ".irq_watcher", "line_watcher");
    platform_->Bind(die + ".driver.socket", die + ".bus.target");
    platform_->Bind(die + ".bus.out0", die + ".link.target");
    platform_->Bind(die + ".bus.out1", die + ".link.sideband");
    platform_->Add(die + ".in", "router",
                   {{"outputs", 2},
                    {"out0.base", kMemoryOnTheOtherDie},
                    {"out0.size", kBlockSize},
                    {"out1.base", kEarsOnTheOtherDie},
                    {"out1.size", kBlockSize}});
    platform_->Add(die + ".memory", "memory", {{"size", kBlockSize}});
    platform_->Bind(die + ".link.initiator", die + ".in.target");
    platform_->Bind(die + ".in.out0", die + ".memory.socket");
    platform_->Bind(die + ".in.out1", die + ".arrivals.socket");
    platform_->Bind(die + ".link.reset", die + ".reset_watcher.line");
    platform_->Bind(die + ".link.irq", die + ".irq_watcher.line");
  }

  std::vector<RecordedAccess> arrived_on_a_;
  std::vector<RecordedAccess> arrived_on_b_;
  std::unique_ptr<Platform> platform_;
  std::function<void(BusDriver&)> on_a_ = [](BusDriver&) {};
  std::function<void(BusDriver&)> on_b_ = [](BusDriver&) {};
};

// Sixty-four bytes, which take 4 ns to go at 16 bytes a nanosecond.
constexpr std::size_t kWriteSize = 64;
std::array<std::uint8_t, kWriteSize> SixtyFourBytes() {
  std::array<std::uint8_t, kWriteSize> bytes{};
  bytes.fill(0xA5);
  return bytes;
}

TEST(WhenALinkIsBuilt, EachEndHoldsItsOwnDieInResetFromTheStart) {
  TwoDiesOnALink dies;
  bool held_at_the_start = false;

  dies.OnTheDies([&](BusDriver& on_a) {
    // One delta cycle in, which is as early as a process can look.
    on_a.WaitFor(sc_core::SC_ZERO_TIME);
    held_at_the_start = dies.ResetOn("b").line.read();
  });

  EXPECT_TRUE(held_at_the_start);
}

TEST(WhenTheMainbandIsUsedBeforeTheLinkIsUp, TheAccessIsRefused) {
  TwoDiesOnALink dies;
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  dies.OnTheDies([&](BusDriver& on_a) {
    response = on_a.Write(kEarsOnTheOtherDie, SixtyFourBytes());
  });

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
}

TEST(WhenTheMainbandIsUsedBeforeTheLinkIsUp, NothingCrosses) {
  TwoDiesOnALink dies;

  dies.OnTheDies([&](BusDriver& on_a) {
    on_a.Write(kEarsOnTheOtherDie, SixtyFourBytes());
  });

  EXPECT_TRUE(dies.ArrivedOnB().empty());
}

TEST(WhenOneDiesFirmwareTrainsTheLink, BothDiesSayItIsUp) {
  TwoDiesOnALink dies;
  bool up_on_a = false;
  bool up_on_b = false;

  dies.OnTheDies(
      [&](BusDriver& on_a) { up_on_a = BringTheLinkUp(on_a, kSideband); },
      [&](BusDriver& on_b) {
        up_on_b = WaitUntilTheLinkIsUp(on_b, kSideband);
      });

  EXPECT_TRUE(up_on_a);
  EXPECT_TRUE(up_on_b);
}

TEST(WhenAWriteCrossesATrainedLink, ItArrivesALatencyAndItsBytesLater) {
  TwoDiesOnALink dies;
  sc_core::sc_time left;

  dies.OnTheDies([&](BusDriver& on_a) {
    BringTheLinkUp(on_a, kSideband);
    left = sc_core::sc_time_stamp();
    on_a.Write(kEarsOnTheOtherDie, SixtyFourBytes());
  });

  // 20 ns to cross, and 4 ns for 64 bytes at 16 bytes a nanosecond.
  ASSERT_EQ(dies.ArrivedOnB().size(), 1U);
  EXPECT_EQ(dies.ArrivedOnB().front().Time() - left,
            sc_core::sc_time(24, sc_core::SC_NS));
}

TEST(WhenTheManagerWritesTheOtherEndsResetRegister, ThatDieIsLetGo) {
  TwoDiesOnALink dies;
  bool still_held = true;

  dies.OnTheDies([&](BusDriver& on_a) {
    BringTheLinkUp(on_a, kSideband);
    LetTheOtherDieGo(on_a, kSideband);
    still_held = !dies.ResetOn("b").WaitForLevel(false, BetweenLooks());
  });

  EXPECT_FALSE(still_held);
}

TEST(WhenTheLinkComesUpAndTheInterruptIsEnabled, TheEndpointInterrupts) {
  TwoDiesOnALink dies;
  bool interrupted = false;

  dies.OnTheDies([&](BusDriver& on_a) {
    on_a.Write32(kSideband + Registers::kNotification,
                 Registers::kStatusChangedInterrupt);
    BringTheLinkUp(on_a, kSideband);
    interrupted = dies.IrqOn("a").WaitForLevel(true, BetweenLooks());
  });

  EXPECT_TRUE(interrupted);
}

TEST(WhenFirmwareClearsTheChangedBit, TheInterruptGoesAway) {
  TwoDiesOnALink dies;
  bool still_interrupting = true;

  dies.OnTheDies([&](BusDriver& on_a) {
    on_a.Write32(kSideband + Registers::kNotification,
                 Registers::kStatusChangedInterrupt);
    BringTheLinkUp(on_a, kSideband);
    on_a.Write32(kSideband + Registers::kLinkStatusRegister,
                 Registers::kLinkStatusChanged);
    still_interrupting = !dies.IrqOn("a").WaitForLevel(false, BetweenLooks());
  });

  EXPECT_FALSE(still_interrupting);
}

TEST(WhenAFaultIsInjectedIntoATrainedLink, TheMainbandStopsCarrying) {
  TwoDiesOnALink dies;
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  dies.OnTheDies([&](BusDriver& on_a) {
    BringTheLinkUp(on_a, kSideband);
    on_a.Write32(kSideband + Registers::kFaultInjection, 1);
    WaitUntilTheLinkIsDown(on_a, kSideband);
    response = on_a.Write(kEarsOnTheOtherDie, SixtyFourBytes());
  });

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
}

TEST(WhenAFaultedLinkIsRetrained, TheMainbandCarriesAgain) {
  TwoDiesOnALink dies;
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;

  dies.OnTheDies([&](BusDriver& on_a) {
    BringTheLinkUp(on_a, kSideband);
    on_a.Write32(kSideband + Registers::kFaultInjection, 1);
    WaitUntilTheLinkIsDown(on_a, kSideband);
    on_a.Write32(kSideband + Registers::kLinkControl, Registers::kRetrainLink);
    WaitUntilTheLinkIsUp(on_a, kSideband);
    response = on_a.Write(kEarsOnTheOtherDie, SixtyFourBytes());
  });

  EXPECT_EQ(response, tlm::TLM_OK_RESPONSE);
}

TEST(WhenADebuggerLooksAcrossALinkThatIsNotUp, ItSeesTheOtherDiesMemory) {
  TwoDiesOnALink dies;
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen{};
  dies.DebugWriteOn("b", kMemoryOnTheOtherDie + 0x10, stored);

  dies.OnTheDies([&](BusDriver& on_a) {
    on_a.DebugRead(kMemoryOnTheOtherDie + 0x10, seen);
  });

  EXPECT_EQ(seen, stored);
}

TEST(WhenAnEndpointsOptionalPortsAreLeftUnconnected, ItStillElaborates) {
  Platform platform{BuiltinComponents()};
  platform.Add("a", "d2d_link_endpoint");
  platform.Add("b", "d2d_link_endpoint");
  platform.Bind("a.peer_initiator", "b.peer_target");
  platform.Bind("b.peer_initiator", "a.peer_target");
  platform.Bind("a.sideband_peer_initiator", "b.sideband_peer_target");
  platform.Bind("b.sideband_peer_initiator", "a.sideband_peer_target");

  EXPECT_NO_THROW(platform.Elaborate());
}

}  // namespace
}  // namespace socpuppet
