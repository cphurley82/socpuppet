#include <stdexcept>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/platform.h"

using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

socpuppet::Factory unused_factory();

TEST(WhenAPlatformIsComposedByName, AMastersWriteReachesTheMemory) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("link", "pass_through_link");
  platform.add("ram", "memory", {{"size", 0x100}});
  platform.bind("cpu.socket", "link.target");
  platform.bind("link.initiator", "ram.socket");
  platform.module<socpuppet::ScriptedBusMaster>("cpu").set_script({socpuppet::Write32{0x10, 0xC0FFEE}});

  sc_core::sc_start();

  EXPECT_EQ(platform.module<socpuppet::Memory>("ram").peek32(0x10), 0xC0FFEEu);
}

TEST(WhenAnUnknownImplementationIsRequested, TheErrorNamesItAndListsTheKnownOnes) {
  socpuppet::Registry registry;
  registry.add("memory", unused_factory());
  registry.add("uart", unused_factory());
  socpuppet::Platform platform{registry};

  EXPECT_THAT([&] { platform.add("ram", "memroy"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("memroy"), HasSubstr("memory"), HasSubstr("uart"))));
}

TEST(WhenTwoPortsOfTheSameRoleAreBound, TheErrorNamesBothPorts) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("link", "pass_through_link");

  EXPECT_THAT([&] { platform.bind("cpu.socket", "link.initiator"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("cpu.socket"), HasSubstr("link.initiator"))));
}

TEST(WhenAPortThatDoesNotExistIsBound, TheErrorListsTheComponentsPorts) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("link", "pass_through_link");

  EXPECT_THAT([&] { platform.bind("cpu.socket", "link.tarket"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("link.tarket"), HasSubstr("target, initiator"))));
}

TEST(WhenAPortIsLeftUnbound, TheWiringCheckFailsAndNamesThePort) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("link", "pass_through_link");
  platform.bind("cpu.socket", "link.target");

  EXPECT_THAT([&] { platform.check_wiring(); },
              ThrowsMessage<std::runtime_error>(HasSubstr("link.initiator")));
}

TEST(WhenAComponentIsAddedInsideAGroup, ItsSimulationNameCarriesTheGroup) {
  socpuppet::Platform platform{socpuppet::builtin_components()};

  platform.add("io.ram", "memory", {{"size", 0x100}});

  EXPECT_STREQ(platform.module<socpuppet::Memory>("io.ram").name(), "io.ram");
}

TEST(WhenAComponentIsAddedInsideNestedGroups, ItsSimulationNameCarriesEveryGroup) {
  socpuppet::Platform platform{socpuppet::builtin_components()};

  platform.add("host.io.ram", "memory", {{"size", 0x100}});

  EXPECT_STREQ(platform.module<socpuppet::Memory>("host.io.ram").name(), "host.io.ram");
}

TEST(WhenAPortOfAnUnknownComponentIsBound, TheErrorNamesItAndListsTheKnownComponents) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("link", "pass_through_link");

  EXPECT_THAT([&] { platform.bind("cpu.socket", "lnik.target"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("lnik"), HasSubstr("cpu, link"))));
}

TEST(WhenARequiredParameterIsMissing, TheErrorNamesTheParameterAndTheImplementation) {
  socpuppet::Platform platform{socpuppet::builtin_components()};

  EXPECT_THAT([&] { platform.add("ram", "memory"); },
              ThrowsMessage<std::invalid_argument>(AllOf(HasSubstr("size"), HasSubstr("memory"))));
}

TEST(WhenTwoComponentsAreGivenTheSameName, TheSecondIsRefusedAndTheErrorNamesIt) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("io.ram", "memory", {{"size", 0x100}});

  EXPECT_THAT([&] { platform.add("io.ram", "memory", {{"size", 0x100}}); },
              ThrowsMessage<std::invalid_argument>(HasSubstr("io.ram")));
}

socpuppet::Factory unused_factory() {
  return [](const char*, const socpuppet::Config&) { return socpuppet::Instance{}; };
}
