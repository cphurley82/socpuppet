#include "socpuppet/platform/tracer.h"

#include <array>
#include <cstdint>
#include <functional>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/trace.h"
#include "socpuppet/models/memory.h"
#include "tests/cpp/contracts/bus_driver.h"

namespace socpuppet {

using ::testing::AllOf;
using ::testing::ElementsAre;
using ::testing::Field;

namespace {

// A BusDriver wired through a tracer into a 0x100-byte RAM.
struct TracedConnection {
  explicit TracedConnection(std::function<void(BusDriver&)> body)
      : driver{"driver", std::move(body)} {
    driver.socket.bind(tracer.target);
    tracer.initiator.bind(memory.socket);
  }

  Trace trace;
  BusDriver driver;
  Tracer tracer{"tracer", "cpu.socket", "ram.socket", trace};
  Memory memory{"memory", 0x100};
};

}  // namespace

TEST(WhenAWriteCrossesATracedConnection,
     TheTraceRecordsWhatWasWrittenWhereAndWhen) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  TracedConnection traced{[&](BusDriver& bus) {
    wait(sc_core::sc_time(10, sc_core::SC_NS));
    bus.Write(0x10, written);
  }};

  sc_core::sc_start();

  EXPECT_THAT(traced.trace.Records(),
              ElementsAre(TraceRecord{.time = Picoseconds{10'000},
                                      .source = "cpu.socket",
                                      .sink = "ram.socket",
                                      .is_write = true,
                                      .address = 0x10,
                                      .data = {0x11, 0x22, 0x33, 0x44},
                                      .ok = true}));
}

TEST(WhenAReadCrossesATracedConnection, TheTraceRecordsTheDataThatCameBack) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> read{};
  TracedConnection traced{[&](BusDriver& bus) { bus.Read(0x10, read); }};
  DebugWrite(traced.memory, 0x10, stored);

  sc_core::sc_start();

  EXPECT_THAT(traced.trace.Records(),
              ElementsAre(AllOf(Field(&TraceRecord::is_write, false),
                                Field(&TraceRecord::data,
                                      ElementsAre(0x11, 0x22, 0x33, 0x44)))));
}

TEST(WhenATracedAccessGetsAnErrorResponse, TheTraceRecordsThatItFailed) {
  std::array<std::uint8_t, 4> data{};
  TracedConnection traced{[&](BusDriver& bus) { bus.Read(0x1000, data); }};

  sc_core::sc_start();

  EXPECT_THAT(traced.trace.Records(),
              ElementsAre(Field(&TraceRecord::ok, false)));
}

TEST(WhenADebugAccessCrossesATracedConnection,
     ItReachesTheTargetButIsNotRecorded) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen{};
  TracedConnection traced{[&](BusDriver& bus) { bus.DebugRead(0x10, seen); }};
  DebugWrite(traced.memory, 0x10, stored);

  sc_core::sc_start();

  EXPECT_EQ(seen, stored);
  EXPECT_TRUE(traced.trace.Records().empty());
}

TEST(WhenDirectMemoryAccessIsAskedForAcrossATracedConnection, ItIsRefused) {
  bool granted = true;
  TracedConnection traced{[&](BusDriver& bus) {
    granted = bus.RequestDirectMemory(0x10).Granted();
  }};

  sc_core::sc_start();

  EXPECT_FALSE(granted);
}

TEST(WhenAnAccessCrossesATracedConnection, DirectMemoryAccessIsNotOffered) {
  const std::array<std::uint8_t, 4> written{};
  std::array<std::uint8_t, 4> read{};
  bool offered_after_write = true;
  bool offered_after_read = true;
  TracedConnection traced{[&](BusDriver& bus) {
    bus.Write(0x10, written);
    offered_after_write = bus.DirectMemoryWasOffered();
    bus.Read(0x10, read);
    offered_after_read = bus.DirectMemoryWasOffered();
  }};

  sc_core::sc_start();

  EXPECT_FALSE(offered_after_write) << "the hint got through on the write";
  EXPECT_FALSE(offered_after_read) << "the hint got through on the read";
}

}  // namespace socpuppet
