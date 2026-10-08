#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/test_components.h"

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
    AddBusDriver(registry, "bus_driver", body);
    AddLineWatcher(registry, "line_watcher");
    return registry;
  }

  bool LineIsHigh() {
    return platform.ModuleAt<LineWatcher>("watcher").line->read();
  }

  Platform platform;
};

// An interrupt message: a 32-bit write whose data is the vector's number.
tlm::tlm_response_status SendMessage(BusDriver& bus, std::uint32_t vector) {
  return bus.Write32(0, vector);
}

// Reads which vectors are waiting: one bit for each, lowest first.
std::uint32_t ReadWaiting(BusDriver& bus) { return bus.Read32(0); }

// The same, by debug access: the way a debugger looks, without the read
// counting as the host taking the vectors.
std::uint32_t LookAtWaiting(BusDriver& bus) {
  std::array<std::uint8_t, 4> bytes{};
  bus.DebugRead(0, bytes);
  return socpuppet::LoadLittleEndian<std::uint32_t>(bytes);
}

}  // namespace

TEST(WhenTheWaitingVectorsAreLookedAtByDebugAccess,
     TheyAreSeenAndStillWaiting) {
  std::uint32_t looked_at = 0;
  std::uint32_t read = 0;
  MasterWithAnMsiReceiver fixture{[&](BusDriver& bus) {
    SendMessage(bus, 1);
    looked_at = LookAtWaiting(bus);
    read = ReadWaiting(bus);
  }};

  fixture.platform.Run();

  EXPECT_EQ(looked_at, 0b10U);
  EXPECT_EQ(read, 0b10U);
}

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
