#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <ostream>
#include <span>
#include <stdexcept>
#include <string>
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
                  AllOf(HasSubstr("spam_line"), HasSubstr("spam.Raise"),
                        HasSubstr("spam.Lower"))));
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

TEST(WhenAParameterTheImplementationDoesNotTakeIsGiven,
     TheErrorNamesItAndTheOnesTheImplementationTakes) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT(
      [&] {
        platform.Add("ram", "memory", {{"size", 0x100}, {"sise", 0x200}});
      },
      ThrowsMessage<std::invalid_argument>(AllOf(HasSubstr("\"memory\""),
                                                 HasSubstr("\"sise\""),
                                                 HasSubstr("\"size\""))));
}

// A parameter value its implementation cannot use: too wide for the
// register field it goes in, or a count or a rate of zero.
struct OutOfRange {
  std::string implementation;
  socpuppet::Config config;
  std::string parameter;
  std::string given;
};

void PrintTo(const OutOfRange& out_of_range, std::ostream* out) {
  *out << out_of_range.implementation << " with " << out_of_range.parameter
       << " = " << out_of_range.given;
}

socpuppet::Config PcieEndpointWith(const std::string& parameter,
                                   std::uint64_t value) {
  socpuppet::Config config{{"vendor_id", 0x1B36},
                           {"device_id", 0x0010},
                           {"class_code", 0x01'08'02},
                           {"function_size", 0x4000},
                           {"vectors", 2}};
  config[parameter] = value;
  return config;
}

class WhenAParameterIsOutOfRange : public ::testing::TestWithParam<OutOfRange> {
};

TEST_P(WhenAParameterIsOutOfRange,
       TheErrorNamesTheImplementationTheParameterAndWhatWasGiven) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT(
      [&] {
        platform.Add("spam", GetParam().implementation, GetParam().config);
      },
      ThrowsMessage<std::invalid_argument>(
          AllOf(HasSubstr("\"" + GetParam().implementation + "\""),
                HasSubstr("\"" + GetParam().parameter + "\""),
                HasSubstr(GetParam().given + " was given"))));
}

INSTANTIATE_TEST_SUITE_P(
    BuiltinComponents, WhenAParameterIsOutOfRange,
    ::testing::Values(
        OutOfRange{"machine_timer", {{"frequency_hz", 0}}, "frequency_hz", "0"},
        OutOfRange{"dbt_rise_cpu",
                   {{"xlen", 32}, {"reset_vector", 0}, {"gdb_port", 65536}},
                   "gdb_port",
                   "65536"},
        OutOfRange{"behavioral_nvme",
                   {{"blocks", 16}, {"vectors", 0}},
                   "vectors",
                   "0"},
        OutOfRange{"behavioral_nvme",
                   {{"blocks", 16}, {"vectors", 2049}},
                   "vectors",
                   "2049"},
        OutOfRange{"msi_plic_bridge", {{"vectors", 0}}, "vectors", "0"},
        OutOfRange{"msi_plic_bridge", {{"vectors", 2049}}, "vectors", "2049"},
        OutOfRange{"pcie_endpoint", PcieEndpointWith("vendor_id", 0x1'0000),
                   "vendor_id", "65536"},
        OutOfRange{"pcie_endpoint", PcieEndpointWith("device_id", 0x1'0000),
                   "device_id", "65536"},
        OutOfRange{"pcie_endpoint", PcieEndpointWith("class_code", 0x100'0000),
                   "class_code", "16777216"},
        OutOfRange{"pcie_endpoint", PcieEndpointWith("vectors", 0), "vectors",
                   "0"},
        OutOfRange{"pcie_endpoint", PcieEndpointWith("vectors", 2049),
                   "vectors", "2049"}));

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

// Gives a platform a master and a memory, bound, and leaves it to the
// caller to elaborate.
void AddAMasterAndAMemory(socpuppet::Platform& platform) {
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("ram", "memory", {{"size", 0x100}});
  platform.Bind("cpu.socket", "ram.socket");
}

TEST(WhenAPlatformIsRunBeforeItIsElaborated, TheErrorSaysToElaborateFirst) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);

  EXPECT_THAT([&] { platform.Run(); },
              ThrowsMessage<std::logic_error>(HasSubstr("Elaborate() first")));
}

TEST(WhenAPlatformIsSteppedBeforeItIsElaborated, TheErrorSaysToElaborateFirst) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);

  EXPECT_THAT([&] { platform.Step(); },
              ThrowsMessage<std::logic_error>(HasSubstr("Elaborate() first")));
}

TEST(WhenADebugAccessIsMadeBeforeThePlatformIsElaborated,
     TheErrorSaysToElaborateFirst) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);
  std::array<std::byte, 4> data{};

  EXPECT_THAT([&] { platform.DebugRead("cpu.socket", 0x10, data); },
              ThrowsMessage<std::logic_error>(HasSubstr("Elaborate() first")));
}

TEST(WhenAPlatformIsElaboratedASecondTime, ItIsRefusedAndTheErrorSaysWhy) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);
  platform.Elaborate();

  EXPECT_THAT([&] { platform.Elaborate(); },
              ThrowsMessage<std::logic_error>(HasSubstr("is elaborated")));
}

TEST(WhenAComponentIsAddedToAnElaboratedPlatform,
     ItIsRefusedAndTheErrorSaysWhy) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);
  platform.Elaborate();

  EXPECT_THAT([&] { platform.Add("more_ram", "memory", {{"size", 0x100}}); },
              ThrowsMessage<std::logic_error>(AllOf(
                  HasSubstr("add a component"), HasSubstr("is elaborated"))));
}

TEST(WhenPortsAreBoundInAnElaboratedPlatform, ItIsRefusedAndTheErrorSaysWhy) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);
  platform.Elaborate();

  EXPECT_THAT([&] { platform.Bind("cpu.irq", "cpu.reset"); },
              ThrowsMessage<std::logic_error>(
                  AllOf(HasSubstr("bind ports"), HasSubstr("is elaborated"))));
}

TEST(WhenAPortIsNamedWithoutItsComponent, TheErrorSaysHowAPortIsNamed) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);

  EXPECT_THAT([&] { platform.Bind("socket", "ram.socket"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("\"socket\" does not name a port"),
                        HasSubstr("\"cpu.socket\""))));
}

TEST(WhenAComponentIsAskedForAsATypeItIsNot, TheErrorNamesBothTypes) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddAMasterAndAMemory(platform);

  EXPECT_THAT([&] { platform.ModuleAt<socpuppet::Memory>("cpu"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("\"cpu\""), HasSubstr("ScriptedBusMaster"),
                        HasSubstr("socpuppet::Memory"))));
}

socpuppet::Factory UnusedFactory() {
  return
      [](const char*, socpuppet::Parameters&) { return socpuppet::Instance{}; };
}

// A component that drives its one wire output from two processes of its
// own. The second write comes a delta cycle after the first: a signal that
// allows many writers only objects to two in one delta cycle, so only a
// signal with one writer refuses this.
struct TwoHanded : sc_core::sc_module {
  sc_core::sc_out<bool> line{"line"};

  explicit TwoHanded(const sc_core::sc_module_name& name) : sc_module(name) {
    SC_THREAD(Raise);
    SC_THREAD(Lower);
  }

  void Raise() { line.write(true); }
  void Lower() {
    wait(sc_core::SC_ZERO_TIME);
    line.write(false);
  }
};

socpuppet::Registry WithSpamThatDrivesItsLineFromTwoProcesses() {
  socpuppet::Registry registry;
  registry.Add("spam", [](const char* name, socpuppet::Parameters&) {
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
  registry.Add("spam", [](const char* name, socpuppet::Parameters&) {
    auto module = std::make_unique<LineDriver>(name, [](LineDriver&) {});
    std::vector<socpuppet::Port> ports{
        socpuppet::WireSourcePort("line", module->line, /*required=*/false)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
}
