#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
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
  platform.module<socpuppet::ScriptedBusMaster>("cpu").set_script(
      {socpuppet::Write32{0x10, 0xC0FFEE}});
  platform.elaborate();

  platform.run();

  std::uint32_t seen = 0;
  platform.debug_read("cpu.socket", 0x10, std::as_writable_bytes(std::span{&seen, 1}));
  EXPECT_EQ(seen, 0xC0FFEEu);
}

TEST(WhenAPlatformIsElaboratedButNotYetRun, DebugWritesAlreadyReachTheMemory) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("ram", "memory", {{"size", 0x100}});
  platform.bind("cpu.socket", "ram.socket");
  platform.elaborate();
  const std::uint32_t written = 0xC0FFEE;
  std::uint32_t seen = 0;

  platform.debug_write("cpu.socket", 0x10, std::as_bytes(std::span{&written, 1}));
  platform.debug_read("cpu.socket", 0x10, std::as_writable_bytes(std::span{&seen, 1}));

  EXPECT_EQ(seen, written);
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

TEST(WhenAPortIsLeftUnbound, ElaborationIsRefusedAndTheErrorNamesThePort) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("link", "pass_through_link");
  platform.bind("cpu.socket", "link.target");

  EXPECT_THAT([&] { platform.elaborate(); },
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

TEST(WhenADebugAccessIsAskedForThroughATargetPort, TheErrorNamesThePort) {
  socpuppet::Platform platform{socpuppet::builtin_components()};
  platform.add("cpu", "scripted_bus_master");
  platform.add("ram", "memory", {{"size", 0x100}});
  platform.bind("cpu.socket", "ram.socket");
  platform.elaborate();
  std::array<std::byte, 4> data{};

  EXPECT_THAT([&] { platform.debug_read("ram.socket", 0x10, data); },
              ThrowsMessage<std::invalid_argument>(HasSubstr("ram.socket")));
}

socpuppet::Factory unused_factory() {
  return [](const char*, const socpuppet::Config&) { return socpuppet::Instance{}; };
}
