#include <array>
#include <cstdint>
#include <functional>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "../contracts/bus_driver.h"
#include "socpuppet/core/trace.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/platform/tracer.h"

using namespace socpuppet;
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

TEST(WhenAWriteCrossesATracedConnection, TheTraceRecordsWhatWasWrittenWhereAndWhen) {
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  TracedConnection traced{[&](BusDriver& bus) {
    wait(sc_core::sc_time(10, sc_core::SC_NS));
    bus.write(0x10, written);
  }};

  sc_core::sc_start();

  EXPECT_THAT(traced.trace.records(),
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
  TracedConnection traced{[&](BusDriver& bus) { bus.read(0x10, read); }};
  debug_write(traced.memory, 0x10, stored);

  sc_core::sc_start();

  EXPECT_THAT(traced.trace.records(),
              ElementsAre(AllOf(Field(&TraceRecord::is_write, false),
                                Field(&TraceRecord::data, ElementsAre(0x11, 0x22, 0x33, 0x44)))));
}

TEST(WhenATracedAccessGetsAnErrorResponse, TheTraceRecordsThatItFailed) {
  std::array<std::uint8_t, 4> data{};
  TracedConnection traced{[&](BusDriver& bus) { bus.read(0x1000, data); }};

  sc_core::sc_start();

  EXPECT_THAT(traced.trace.records(), ElementsAre(Field(&TraceRecord::ok, false)));
}

TEST(WhenADebugAccessCrossesATracedConnection, ItReachesTheTargetButIsNotRecorded) {
  const std::array<std::uint8_t, 4> stored{0x11, 0x22, 0x33, 0x44};
  std::array<std::uint8_t, 4> seen{};
  TracedConnection traced{[&](BusDriver& bus) { bus.debug_read(0x10, seen); }};
  debug_write(traced.memory, 0x10, stored);

  sc_core::sc_start();

  EXPECT_EQ(seen, stored);
  EXPECT_TRUE(traced.trace.records().empty());
}

TEST(WhenDirectMemoryAccessIsAskedForAcrossATracedConnection, ItIsRefused) {
  bool granted = true;
  TracedConnection traced{[&](BusDriver& bus) { granted = bus.direct_memory(0x10).granted(); }};

  sc_core::sc_start();

  EXPECT_FALSE(granted);
}
