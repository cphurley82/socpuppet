#ifndef TESTS_CPP_CONTRACTS_BUS_MASTER_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_BUS_MASTER_CONTRACT_H_

#include <cstdint>
#include <memory>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/support/line_driver.h"
#include "tests/cpp/support/recording_target.h"

// What a test asks a bus master to do. Each kind of master has its own way
// of being told: a script for the stand-in, a program for a CPU.
enum class Behavior {
  // Write once to the probe, and then have nothing left to do.
  kWriteToTheProbe,
};

// What every bus master must do, whether it is a CPU model running a
// program or the stand-in playing a script.
//
// To hold a master to this contract, write a rig for it and
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, BusMasterContract,
//                                  ::testing::Types<MyRig>);
// A rig says how to make the master do things:
//   static const char* Implementation();   its name in the registry. The
//       master must have a bus port called "socket" and a wire input
//       called "reset".
//   static socpuppet::Config Config();     what it is created with
//   static void Load(socpuppet::Platform&, Behavior);
//       gives the master at "cpu" something to run. Programs go at
//       kProgramBase, which is where Config() must make a CPU start.
template <typename Rig>
class BusMasterContract : public ::testing::Test {
 public:
  // Where the platform has a RAM for a master's program.
  static constexpr std::uint64_t kProgramBase = 0x8000'0000;
  // Where it has the probe: a target that records every access it gets.
  static constexpr std::uint64_t kProbeBase = 0x1000'0000;

 protected:
  static sc_core::sc_time Microseconds(double count) {
    return {count, sc_core::SC_US};
  }

  // What a test's scenario sets. Everything else is the same every time.
  struct Scenario {
    Behavior behavior;
    // What drives the master's reset input. Left unconnected if empty.
    Drive reset = nullptr;
  };

  // Builds the platform: the master at "cpu", with a RAM and the probe
  // behind a router.
  void Build(const Scenario& scenario) {
    const Drive& reset = scenario.reset;
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    registry.Add("probe", [this](const char* name, const socpuppet::Config&) {
      auto module = std::make_unique<RecordingTarget>(name, probed_);
      std::vector<socpuppet::Port> ports{
          socpuppet::TargetPort("socket", module->socket)};
      return socpuppet::Instance{.module = std::move(module),
                                 .ports = std::move(ports)};
    });
    registry.Add("line_driver",
                 [reset](const char* name, const socpuppet::Config&) {
                   auto module = std::make_unique<LineDriver>(name, reset);
                   std::vector<socpuppet::Port> ports{
                       socpuppet::WireSourcePort("line", module->line)};
                   return socpuppet::Instance{.module = std::move(module),
                                              .ports = std::move(ports)};
                 });
    platform_ = std::make_unique<socpuppet::Platform>(std::move(registry));
    platform_->Add("cpu", Rig::Implementation(), Rig::Config());
    platform_->Add("bus", "router",
                   {{"outputs", 2},
                    {"out0.base", kProgramBase},
                    {"out0.size", 0x1000},
                    {"out1.base", kProbeBase},
                    {"out1.size", 0x100}});
    platform_->Add("ram", "memory", {{"size", 0x1000}});
    platform_->Add("probe", "probe");
    platform_->Bind("cpu.socket", "bus.target");
    platform_->Bind("bus.out0", "ram.socket");
    platform_->Bind("bus.out1", "probe.socket");
    if (reset) {
      platform_->Add("reset_driver", "line_driver");
      platform_->Bind("reset_driver.line", "cpu.reset");
    }
    platform_->Elaborate();
    Rig::Load(*platform_, scenario.behavior);
  }

  // Runs for long enough that any behavior here has finished: each is a
  // handful of bus accesses or instructions, and the tests' own waits are a
  // few microseconds.
  void RunToTheEnd() { platform_->Run(sc_core::sc_time{1, sc_core::SC_MS}); }

  // Every access the probe has received.
  std::vector<RecordedAccess> probed_;
  // Made by Build(), once the test has said what its scenario is.
  std::unique_ptr<socpuppet::Platform> platform_;
};

TYPED_TEST_SUITE_P(BusMasterContract);

TYPED_TEST_P(BusMasterContract, WhileResetIsHighTheMasterWaitsAndThenStarts) {
  const sc_core::sc_time released_at = this->Microseconds(5);
  this->Build(
      {.behavior = Behavior::kWriteToTheProbe, .reset = [&](LineDriver& reset) {
         reset.Set(true);
         reset.WaitFor(released_at);
         reset.Set(false);
       }});

  this->RunToTheEnd();

  EXPECT_THAT(this->probed_, ::testing::ElementsAre(::testing::Field(
                                 "kernel_time", &RecordedAccess::kernel_time,
                                 ::testing::Ge(released_at))));
}

TYPED_TEST_P(BusMasterContract, WhenResetIsRaisedAgainTheMasterStartsOver) {
  const sc_core::sc_time raised_again_at = this->Microseconds(20);
  const sc_core::sc_time released_again_at = this->Microseconds(25);
  this->Build(
      {.behavior = Behavior::kWriteToTheProbe, .reset = [&](LineDriver& reset) {
         // By now the master has done what it was given to do.
         reset.WaitFor(raised_again_at);
         reset.Set(true);
         reset.WaitFor(released_again_at - raised_again_at);
         reset.Set(false);
       }});

  this->RunToTheEnd();

  EXPECT_THAT(this->probed_,
              ::testing::ElementsAre(
                  ::testing::Field("kernel_time", &RecordedAccess::kernel_time,
                                   ::testing::Lt(raised_again_at)),
                  ::testing::Field("kernel_time", &RecordedAccess::kernel_time,
                                   ::testing::Ge(released_again_at))));
}

TYPED_TEST_P(BusMasterContract, WithNothingConnectedToItsInputsTheMasterRuns) {
  this->Build({.behavior = Behavior::kWriteToTheProbe});

  this->RunToTheEnd();

  EXPECT_THAT(this->probed_, ::testing::SizeIs(1));
}

TYPED_TEST_P(BusMasterContract, AMasterWithNothingLeftToDoLetsTheRunEnd) {
  this->Build({.behavior = Behavior::kWriteToTheProbe});

  // A run with no time limit, which only returns once nothing is scheduled.
  this->platform_->Run();

  EXPECT_THAT(this->probed_, ::testing::SizeIs(1));
}

REGISTER_TYPED_TEST_SUITE_P(BusMasterContract,
                            WhileResetIsHighTheMasterWaitsAndThenStarts,
                            WhenResetIsRaisedAgainTheMasterStartsOver,
                            WithNothingConnectedToItsInputsTheMasterRuns,
                            AMasterWithNothingLeftToDoLetsTheRunEnd);

#endif  // TESTS_CPP_CONTRACTS_BUS_MASTER_CONTRACT_H_
