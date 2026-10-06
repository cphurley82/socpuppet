#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
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
// BusDriver as the bus master. `body` is what the driver does. With a
// `second_body`, a second BusDriver is on the router's second input.
struct RoutedPlatform {
  static constexpr std::uint64_t kLowRamBase = 0x1000;
  static constexpr std::uint64_t kHighRamBase = 0x8000'0000;
  static constexpr std::uint64_t kUnmapped = 0x4000;

  explicit RoutedPlatform(
      const std::function<void(BusDriver&)>& body,
      const std::function<void(BusDriver&)>& second_body = nullptr)
      : platform{WithBusDrivers(body, second_body)} {
    platform.Add("cpu", "bus_driver");
    platform.Add("bus", "router",
                 {{"inputs", second_body ? 2 : 1},
                  {"outputs", 2},
                  {"out0.base", kLowRamBase},
                  {"out0.size", 0x100},
                  {"out1.base", kHighRamBase},
                  {"out1.size", 0x100}});
    platform.Add("low_ram", "memory", {{"size", 0x100}});
    platform.Add("high_ram", "memory", {{"size", 0x100}});
    platform.Bind("cpu.socket", "bus.target");
    if (second_body) {
      platform.Add("second_cpu", "second_bus_driver");
      platform.Bind("second_cpu.socket", "bus.in1");
    }
    platform.Bind("bus.out0", "low_ram.socket");
    platform.Bind("bus.out1", "high_ram.socket");
    platform.Elaborate();
  }

  // What the first master finds at `address`, without simulating.
  std::array<std::uint8_t, 4> Peek(std::uint64_t address) {
    std::array<std::uint8_t, 4> seen{};
    platform.DebugRead("cpu.socket", address,
                       std::as_writable_bytes(std::span{seen}));
    return seen;
  }

  static socpuppet::Registry WithBusDrivers(
      const std::function<void(BusDriver&)>& body,
      const std::function<void(BusDriver&)>& second_body) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    for (const auto& [implementation, each] :
         {std::pair{"bus_driver", body},
          std::pair{"second_bus_driver", second_body}}) {
      registry.Add(implementation,
                   [each](const char* name, const socpuppet::Config&) {
                     auto module = std::make_unique<BusDriver>(name, each);
                     std::vector<socpuppet::Port> ports{
                         socpuppet::InitiatorPort("socket", module->socket)};
                     return socpuppet::Instance{.module = std::move(module),
                                                .ports = std::move(ports)};
                   });
    }
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
    bus.Write(RoutedPlatform::kHighRamBase + 0x10, written);
    bus.Read(RoutedPlatform::kHighRamBase + 0x10, read);
  }};

  routed.platform.Run();

  EXPECT_EQ(read, written);
}

TEST(WhenAnAccessFallsInsideAMappedRange, TheOtherTargetsDoNotSeeIt) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> low_ram_contents{0xAA, 0xAA, 0xAA, 0xAA};
  RoutedPlatform routed{[&](BusDriver& bus) {
    bus.Write(RoutedPlatform::kHighRamBase + 0x10, written);
    bus.Read(RoutedPlatform::kLowRamBase + 0x10, low_ram_contents);
  }};

  routed.platform.Run();

  EXPECT_EQ(low_ram_contents, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

TEST(WhenAnAccessHitsNoMappedRange, ItGetsAnAddressErrorResponse) {
  std::array<std::uint8_t, 4> data{};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  RoutedPlatform routed{[&](BusDriver& bus) {
    response = bus.Read(RoutedPlatform::kUnmapped, data);
  }};

  routed.platform.Run();

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TEST(WhenAMasterOnARoutersSecondInputWritesToAMappedAddress,
     TheFirstMasterFindsTheWriteAtThatAddress) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  RoutedPlatform routed{[](BusDriver&) {},
                        [&](BusDriver& second_bus) {
                          second_bus.Write(RoutedPlatform::kHighRamBase + 0x10,
                                           written);
                        }};

  routed.platform.Run();

  EXPECT_EQ(routed.Peek(RoutedPlatform::kHighRamBase + 0x10), written);
}
