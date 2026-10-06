#include <array>
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
#include "tests/cpp/support/line_watcher.h"

namespace socpuppet {

namespace {

// A bus master wired straight to an MSI receiver, with a test's eyes on
// the receiver's interrupt line. `body` is what the master does.
struct MasterWithAnMsiReceiver {
  explicit MasterWithAnMsiReceiver(const std::function<void(BusDriver&)>& body)
      : platform{WithADriverAndAWatcher(body)} {
    platform.Add("driver", "bus_driver");
    platform.Add("receiver", "msi_receiver");
    platform.Add("watcher", "line_watcher");
    platform.Bind("driver.socket", "receiver.socket");
    platform.Bind("receiver.irq", "watcher.line");
    platform.Elaborate();
  }

  static Registry WithADriverAndAWatcher(
      const std::function<void(BusDriver&)>& body) {
    Registry registry = BuiltinComponents();
    registry.Add("bus_driver", [body](const char* name, const Config&) {
      auto module = std::make_unique<BusDriver>(name, body);
      std::vector<Port> ports{InitiatorPort("socket", module->socket)};
      return Instance{.module = std::move(module), .ports = std::move(ports)};
    });
    registry.Add("line_watcher", [](const char* name, const Config&) {
      auto module = std::make_unique<LineWatcher>(name);
      std::vector<Port> ports{WireSinkPort("line", module->line)};
      return Instance{.module = std::move(module), .ports = std::move(ports)};
    });
    return registry;
  }

  bool LineIsHigh() {
    return platform.ModuleAt<LineWatcher>("watcher").line->read();
  }

  Platform platform;
};

// An interrupt message: a 32-bit write whose data is the vector's number.
tlm::tlm_response_status SendMessage(BusDriver& bus, std::uint32_t vector) {
  return bus.Write(0, std::array<std::uint8_t, 4>{
                          static_cast<std::uint8_t>(vector),
                          static_cast<std::uint8_t>(vector >> 8), 0, 0});
}

// Reads which vectors are waiting: one bit for each, lowest first.
std::uint32_t ReadWaiting(BusDriver& bus) {
  std::array<std::uint8_t, 4> bytes{};
  bus.Read(0, bytes);
  return bytes[0] | std::uint32_t{bytes[1]} << 8 |
         std::uint32_t{bytes[2]} << 16 | std::uint32_t{bytes[3]} << 24;
}

}  // namespace

TEST(WhenAMessageArrivesAtAnMsiReceiver, ItsInterruptLineRises) {
  MasterWithAnMsiReceiver fixture{[](BusDriver& bus) { SendMessage(bus, 1); }};

  fixture.platform.Run();

  EXPECT_TRUE(fixture.LineIsHigh());
}

TEST(WhenTheHostReadsAnMsiReceiver, ItLearnsWhichVectorsAreWaiting) {
  std::uint32_t waiting = 0;
  MasterWithAnMsiReceiver fixture{[&](BusDriver& bus) {
    SendMessage(bus, 1);
    SendMessage(bus, 3);
    waiting = ReadWaiting(bus);
  }};

  fixture.platform.Run();

  EXPECT_EQ(waiting, 0b1010U);
}

TEST(WhenTheHostReadsAnMsiReceiverWhoseLineIsHigh, TheLineFalls) {
  MasterWithAnMsiReceiver fixture{[](BusDriver& bus) {
    SendMessage(bus, 1);
    // The host reads because it was interrupted: time for the line to rise.
    bus.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
    ReadWaiting(bus);
  }};

  fixture.platform.Run();

  // It rose, once, and is low now.
  EXPECT_EQ(fixture.platform.ModuleAt<LineWatcher>("watcher").Rises(), 1);
  EXPECT_FALSE(fixture.LineIsHigh());
}

TEST(WhenAnAccessToAnMsiReceiverIsNot32BitsWide, ItGetsAnAddressError) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  MasterWithAnMsiReceiver fixture{[&](BusDriver& bus) {
    response = bus.Write(0, std::array<std::uint8_t, 2>{1, 0});
  }};

  fixture.platform.Run();

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TEST(WhenTheHostReadsAnMsiReceiverASecondTime, NothingIsWaitingAnyMore) {
  std::uint32_t waiting = 1;
  MasterWithAnMsiReceiver fixture{[&](BusDriver& bus) {
    SendMessage(bus, 1);
    ReadWaiting(bus);
    waiting = ReadWaiting(bus);
  }};

  fixture.platform.Run();

  EXPECT_EQ(waiting, 0U);
}

TEST(WhenAMessageNamesAVectorAnMsiReceiverHasNoBitFor, ItIsRefused) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  MasterWithAnMsiReceiver fixture{
      [&](BusDriver& bus) { response = SendMessage(bus, 32); }};

  fixture.platform.Run();

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
}

TEST(WhenAnAccessIsBesideAnMsiReceiversRegister, ItGetsAnAddressError) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  MasterWithAnMsiReceiver fixture{[&](BusDriver& bus) {
    response = bus.Write(4, std::array<std::uint8_t, 4>{1, 0, 0, 0});
  }};

  fixture.platform.Run();

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

}  // namespace socpuppet
