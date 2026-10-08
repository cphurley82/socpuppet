#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <stdexcept>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/support/line_driver.h"

using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

socpuppet::Factory UnusedFactory();
socpuppet::Registry WithSpamThatHasAnOptionalWireOutput();
socpuppet::Registry WithSpamThatDrivesItsLineFromTwoProcesses();

TEST(WhenAPlatformIsComposedByName, AMastersWriteReachesTheMemory) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("near", "pass_through_link_endpoint");
  platform.Add("far", "pass_through_link_endpoint");
  platform.Add("ram", "memory", {{"size", 0x100}});
  platform.Bind("cpu.socket", "near.target");
  platform.Bind("near.peer_initiator", "far.peer_target");
  platform.Bind("far.peer_initiator", "near.peer_target");
  platform.Bind("far.initiator", "ram.socket");
  platform.ModuleAt<socpuppet::ScriptedBusMaster>("cpu").SetScript(
      []() -> socpuppet::Script {
        co_await socpuppet::Write32(0x10, 0xC0FFEE);
      });
  platform.Elaborate();

  platform.Run();

  std::uint32_t seen = 0;
  platform.DebugRead("cpu.socket", 0x10,
                     std::as_writable_bytes(std::span{&seen, 1}));
  EXPECT_EQ(seen, 0xC0FFEEU);
}

TEST(WhenAPlatformIsElaboratedButNotYetRun, DebugWritesAlreadyReachTheMemory) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("ram", "memory", {{"size", 0x100}});
  platform.Bind("cpu.socket", "ram.socket");
  platform.Elaborate();
  const std::uint32_t written = 0xC0FFEE;
  std::uint32_t seen = 0;

  platform.DebugWrite("cpu.socket", 0x10,
                      std::as_bytes(std::span{&written, 1}));
  platform.DebugRead("cpu.socket", 0x10,
                     std::as_writable_bytes(std::span{&seen, 1}));

  EXPECT_EQ(seen, written);
}

TEST(WhenAnUnknownImplementationIsRequested,
     TheErrorNamesItAndListsTheKnownOnes) {
  socpuppet::Registry registry;
  registry.Add("memory", UnusedFactory());
  registry.Add("uart", UnusedFactory());
  socpuppet::Platform platform{registry};

  EXPECT_THAT(
      [&] { platform.Add("ram", "memroy"); },
      ThrowsMessage<std::invalid_argument>(
          AllOf(HasSubstr("memroy"), HasSubstr("memory"), HasSubstr("uart"))));
}

TEST(WhenTwoPortsOfTheSameRoleAreBound, TheErrorNamesBothPorts) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("link", "pass_through_link_endpoint");

  EXPECT_THAT([&] { platform.Bind("cpu.socket", "link.initiator"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("cpu.socket"), HasSubstr("link.initiator"))));
}

TEST(WhenAPortThatDoesNotExistIsBound, TheErrorListsTheComponentsPorts) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("link", "pass_through_link_endpoint");

  EXPECT_THAT([&] { platform.Bind("cpu.socket", "link.tarket"); },
              ThrowsMessage<std::invalid_argument>(AllOf(
                  HasSubstr("link.tarket"), HasSubstr("target, initiator"))));
}

TEST(WhenAPortIsLeftUnbound, ElaborationIsRefusedAndTheErrorNamesThePort) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("link", "pass_through_link_endpoint");
  platform.Bind("cpu.socket", "link.target");

  EXPECT_THAT(
      [&] { platform.Elaborate(); },
      ThrowsMessage<std::runtime_error>(HasSubstr("link.peer_initiator")));
}

TEST(WhenAnOptionalWireOutputIsLeftUnconnected, ThePlatformStillElaborates) {
  socpuppet::Platform platform{WithSpamThatHasAnOptionalWireOutput()};
  platform.Add("spam", "spam");

  EXPECT_NO_THROW(platform.Elaborate());
}

TEST(WhenAComponentDrivesAWireFromTwoOfItsProcesses,
     TheRunFailsNamingTheWireAndBothProcesses) {
  socpuppet::Platform platform{WithSpamThatDrivesItsLineFromTwoProcesses()};
  platform.Add("spam", "spam");
  platform.Elaborate();

  EXPECT_THAT([&] { platform.Run(); },
              ThrowsMessage<sc_core::sc_report>(
                  AllOf(HasSubstr("spam_line"), HasSubstr("spam.raise"),
                        HasSubstr("spam.lower"))));
}

TEST(WhenAComponentIsAddedInsideAGroup, ItsSimulationNameCarriesTheGroup) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  platform.Add("io.ram", "memory", {{"size", 0x100}});

  EXPECT_STREQ(platform.ModuleAt<socpuppet::Memory>("io.ram").name(), "io.ram");
}

TEST(WhenAComponentIsAddedInsideNestedGroups,
     ItsSimulationNameCarriesEveryGroup) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  platform.Add("host.io.ram", "memory", {{"size", 0x100}});

  EXPECT_STREQ(platform.ModuleAt<socpuppet::Memory>("host.io.ram").name(),
               "host.io.ram");
}

TEST(WhenAPortOfAnUnknownComponentIsBound,
     TheErrorNamesItAndListsTheKnownComponents) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("link", "pass_through_link_endpoint");

  EXPECT_THAT([&] { platform.Bind("cpu.socket", "lnik.target"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("lnik"), HasSubstr("cpu, link"))));
}

TEST(WhenARequiredParameterIsMissing,
     TheErrorNamesTheParameterAndTheImplementation) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT([&] { platform.Add("ram", "memory"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("size"), HasSubstr("memory"))));
}

TEST(WhenTwoComponentsAreGivenTheSameName,
     TheSecondIsRefusedAndTheErrorNamesIt) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("io.ram", "memory", {{"size", 0x100}});

  EXPECT_THAT([&] { platform.Add("io.ram", "memory", {{"size", 0x100}}); },
              ThrowsMessage<std::invalid_argument>(HasSubstr("io.ram")));
}

TEST(WhenADebugAccessIsAskedForThroughATargetPort, TheErrorNamesThePort) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("ram", "memory", {{"size", 0x100}});
  platform.Bind("cpu.socket", "ram.socket");
  platform.Elaborate();
  std::array<std::byte, 4> data{};

  EXPECT_THAT([&] { platform.DebugRead("ram.socket", 0x10, data); },
              ThrowsMessage<std::invalid_argument>(HasSubstr("ram.socket")));
}

socpuppet::Factory UnusedFactory() {
  return [](const char*, const socpuppet::Config&) {
    return socpuppet::Instance{};
  };
}

// A component that drives its one wire output from two processes of its
// own. The second write comes a delta cycle after the first: a signal that
// allows many writers only objects to two in one delta cycle, so only a
// signal with one writer refuses this.
struct TwoHanded : sc_core::sc_module {
  sc_core::sc_out<bool> line{"line"};

  explicit TwoHanded(const sc_core::sc_module_name& name) : sc_module(name) {
    SC_THREAD(raise);
    SC_THREAD(lower);
  }

  void raise() { line.write(true); }
  void lower() {
    wait(sc_core::SC_ZERO_TIME);
    line.write(false);
  }
};

socpuppet::Registry WithSpamThatDrivesItsLineFromTwoProcesses() {
  socpuppet::Registry registry;
  registry.Add("spam", [](const char* name, const socpuppet::Config&) {
    auto module = std::make_unique<TwoHanded>(name);
    std::vector<socpuppet::Port> ports{
        socpuppet::WireSourcePort("line", module->line, /*required=*/false)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
}

// "spam" is a component with one wire output, `line`, that need not be
// connected.
socpuppet::Registry WithSpamThatHasAnOptionalWireOutput() {
  socpuppet::Registry registry;
  registry.Add("spam", [](const char* name, const socpuppet::Config&) {
    auto module = std::make_unique<LineDriver>(name, [](LineDriver&) {});
    std::vector<socpuppet::Port> ports{
        socpuppet::WireSourcePort("line", module->line, /*required=*/false)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
}
