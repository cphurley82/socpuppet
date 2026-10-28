#include "socpuppet/models/rtc.h"

#include <cstdint>
#include <functional>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/regs/rtc.h"
#include "tests/cpp/support/bus_driver.h"

// What socpuppet relies on of its real-time clock in a simulation: that it
// keeps the simulation's time, and its alarm raises its line at the time it
// was set for. What the registers mean is held in
// tests/cpp/unit/rtc_logic_test.cpp.

namespace {

// 2026-10-26 at midnight, in nanoseconds since 1970.
constexpr std::uint64_t kGiven = 1'792'972'800'000'000'000ULL;
constexpr std::uint64_t kASecond = 1'000'000'000ULL;
const sc_core::sc_time kOneSecond{1, sc_core::SC_SEC};
const sc_core::sc_time kAMicrosecond{1, sc_core::SC_US};

// A clock given kGiven, a test's thread at its registers, and its
// interrupt line, which `line`, if given, is pointed at for the thread.
struct Rig {
  Rig(const std::function<void(BusDriver&)>& at_the_registers,
      sc_core::sc_signal<bool>** line = nullptr)
      : registers{"registers", [&](BusDriver& bus) {
                    at_the_registers(bus);
                    sc_core::sc_stop();
                  }} {
    if (line != nullptr) *line = &irq;
    registers.socket.bind(rtc.cpu);
    rtc.irq.bind(irq);
    sc_core::sc_start();
  }

  socpuppet::Rtc rtc{"rtc", kGiven};
  BusDriver registers;
  sc_core::sc_signal<bool> irq{"irq"};
};

// The time, as Linux's rtc-goldfish reads it.
std::uint64_t ReadTime(BusDriver& bus) {
  const std::uint64_t low = bus.Read32(RTC_TIME_LOW);
  const std::uint64_t high = bus.Read32(RTC_TIME_HIGH);
  return high << 32 | low;
}

// Sets the alarm as Linux's rtc-goldfish does: the high half first, since
// writing the low half sets it.
void SetAlarm(BusDriver& bus, std::uint64_t at) {
  bus.Write32(RTC_ALARM_HIGH, static_cast<std::uint32_t>(at >> 32));
  bus.Write32(RTC_ALARM_LOW, static_cast<std::uint32_t>(at));
}

TEST(AClockInASimulation, ReadsAsTheTimeItWasGivenAndTheSimulatedTimeSince) {
  std::uint64_t time = 0;

  Rig rig{[&](BusDriver& bus) {
    bus.WaitFor(3 * kOneSecond);
    time = ReadTime(bus);
  }};

  EXPECT_EQ(time, kGiven + 3 * kASecond);
}

TEST(AClocksAlarm, RaisesItsInterruptLineAtTheTimeItWasSetFor) {
  sc_core::sc_signal<bool>* line = nullptr;
  bool before = true;
  bool after = false;

  Rig rig{[&](BusDriver& bus) {
            bus.Write32(RTC_IRQ_ENABLED, RTC_IRQ_ENABLED_ENABLED);
            SetAlarm(bus, kGiven + kASecond);
            bus.WaitFor(kOneSecond - kAMicrosecond);
            before = line->read();
            bus.WaitFor(2 * kAMicrosecond);
            after = line->read();
          },
          &line};

  EXPECT_FALSE(before);
  EXPECT_TRUE(after);
}

}  // namespace
