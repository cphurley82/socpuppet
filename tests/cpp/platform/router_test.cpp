#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/contracts/bus_driver.h"

namespace {

// A platform with one router in front of two 0x100-byte RAMs, and a test's
// BusDriver as the bus master. `body` is what the driver does.
struct RoutedPlatform {
  static constexpr std::uint64_t low_ram_base = 0x1000;
  static constexpr std::uint64_t high_ram_base = 0x8000'0000;
  static constexpr std::uint64_t unmapped = 0x4000;

  explicit RoutedPlatform(const std::function<void(BusDriver&)>& body)
      : platform{with_bus_driver(body)} {
    platform.add("cpu", "bus_driver");
    platform.add("bus", "router",
                 {{"outputs", 2},
                  {"out0.base", low_ram_base},
                  {"out0.size", 0x100},
                  {"out1.base", high_ram_base},
                  {"out1.size", 0x100}});
    platform.add("low_ram", "memory", {{"size", 0x100}});
    platform.add("high_ram", "memory", {{"size", 0x100}});
    platform.bind("cpu.socket", "bus.target");
    platform.bind("bus.out0", "low_ram.socket");
    platform.bind("bus.out1", "high_ram.socket");
    platform.elaborate();
  }

  static socpuppet::Registry with_bus_driver(
      const std::function<void(BusDriver&)>& body) {
    socpuppet::Registry registry = socpuppet::builtin_components();
    registry.add("bus_driver",
                 [body](const char* name, const socpuppet::Config&) {
                   auto module = std::make_unique<BusDriver>(name, body);
                   std::vector<socpuppet::Port> ports{
                       socpuppet::initiator_port("socket", module->socket)};
                   return socpuppet::Instance{.module = std::move(module),
                                              .ports = std::move(ports)};
                 });
    return registry;
  }

  socpuppet::Platform platform;
};

}  // namespace

TEST(WhenAnAccessFallsInsideAMappedRange,
     ItReachesThatTargetAtTheOffsetWithinTheRange) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> read{};
  RoutedPlatform routed{[&](BusDriver& bus) {
    // A 0x100-byte RAM can only take this access if the router has turned
    // the bus address into an offset from the start of the range.
    bus.write(RoutedPlatform::high_ram_base + 0x10, written);
    bus.read(RoutedPlatform::high_ram_base + 0x10, read);
  }};

  routed.platform.run();

  EXPECT_EQ(read, written);
}

TEST(WhenAnAccessFallsInsideAMappedRange, TheOtherTargetsDoNotSeeIt) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> low_ram_contents{0xAA, 0xAA, 0xAA, 0xAA};
  RoutedPlatform routed{[&](BusDriver& bus) {
    bus.write(RoutedPlatform::high_ram_base + 0x10, written);
    bus.read(RoutedPlatform::low_ram_base + 0x10, low_ram_contents);
  }};

  routed.platform.run();

  EXPECT_EQ(low_ram_contents, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

TEST(WhenAnAccessHitsNoMappedRange, ItGetsAnAddressErrorResponse) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  RoutedPlatform routed{[&](BusDriver& bus) {
    response = bus.read(RoutedPlatform::unmapped, data);
  }};

  routed.platform.run();

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}
