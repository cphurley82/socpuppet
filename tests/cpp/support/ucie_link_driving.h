#ifndef TESTS_CPP_SUPPORT_UCIE_LINK_DRIVING_H_
#define TESTS_CPP_SUPPORT_UCIE_LINK_DRIVING_H_

#include <cstdint>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/ucie_link_registers.h"
#include "socpuppet/core/ucie_sideband.h"
#include "socpuppet/regs/ucie_link.h"
#include "tests/cpp/support/bus_driver.h"

// Driving a die-to-die link from a die's bus, the way its firmware does.
// `base` is where that die's bus has the link's register block.

// Longer than any link in these tests takes to come up: UCIe's 4 ms reset
// hold, plus the longest training time any of them is built with, and
// room to spare.
inline sc_core::sc_time LongEnoughToTrain() {
  return sc_core::sc_time{20, sc_core::SC_MS};
}

// How long firmware waits between looks at a register it is watching.
inline sc_core::sc_time BetweenLooks() {
  return sc_core::sc_time{10, sc_core::SC_US};
}

// Asks the link to train, which is all firmware has to do to start it.
inline void StartTrainingTheLink(BusDriver& bus, std::uint64_t base) {
  bus.Write32(base + UCIE_LINK_CONTROL, UCIE_LINK_CONTROL_START_TRAINING);
}

// Whether the link says it is up.
inline bool TheLinkIsUp(BusDriver& bus, std::uint64_t base) {
  return (bus.Read32(base + UCIE_LINK_STATUS) & UCIE_LINK_STATUS_UP) != 0;
}

// Waits until the link says it is up, as firmware polling its status
// register would, and says whether it ever did.
inline bool WaitUntilTheLinkIsUp(BusDriver& bus, std::uint64_t base) {
  const sc_core::sc_time give_up =
      sc_core::sc_time_stamp() + LongEnoughToTrain();
  while (!TheLinkIsUp(bus, base)) {
    if (sc_core::sc_time_stamp() >= give_up) return false;
    bus.WaitFor(BetweenLooks());
  }
  return true;
}

// Waits until the link says it is no longer up, as firmware watching a
// link it has just faulted would, and says whether it ever did.
inline bool WaitUntilTheLinkIsDown(BusDriver& bus, std::uint64_t base) {
  const sc_core::sc_time give_up =
      sc_core::sc_time_stamp() + LongEnoughToTrain();
  while (TheLinkIsUp(bus, base)) {
    if (sc_core::sc_time_stamp() >= give_up) return false;
    bus.WaitFor(BetweenLooks());
  }
  return true;
}

// Trains the link from this die and returns once it is up, or says that it
// never came up.
inline bool BringTheLinkUp(BusDriver& bus, std::uint64_t base) {
  StartTrainingTheLink(bus, base);
  return WaitUntilTheLinkIsUp(bus, base);
}

// Asks the other die for one of its registers, and waits for the answer.
// A sideband request takes no simulated time: what it waits for is the
// delta cycles the two ends need to pass the packets between them.
inline void AskTheOtherDie(BusDriver& bus, std::uint64_t base,
                           socpuppet::SidebandOpcode opcode,
                           std::uint32_t address, std::uint32_t data = 0) {
  constexpr int kEnoughDeltaCycles = 10;
  bus.Write32(base + UCIE_LINK_MAILBOX_OPCODE,
              static_cast<std::uint32_t>(opcode)
                  << UCIE_LINK_MAILBOX_OPCODE_CODE_SHIFT);
  bus.Write32(base + UCIE_LINK_MAILBOX_ADDRESS, address);
  bus.Write32(base + UCIE_LINK_MAILBOX_DATA, data);
  bus.Write32(base + UCIE_LINK_MAILBOX_TRIGGER, UCIE_LINK_MAILBOX_TRIGGER_GO);
  for (int look = 0; look < kEnoughDeltaCycles; ++look) {
    if ((bus.Read32(base + UCIE_LINK_MAILBOX_STATUS) &
         UCIE_LINK_MAILBOX_STATUS_BUSY) == 0) {
      return;
    }
    bus.WaitFor(sc_core::SC_ZERO_TIME);
  }
  ADD_FAILURE() << "the other die never answered";
}

// Lets the other die out of reset, which is a write of zero to the reset
// register at the other end of the link.
inline void LetTheOtherDieGo(BusDriver& bus, std::uint64_t base) {
  AskTheOtherDie(bus, base, socpuppet::SidebandOpcode::kMemoryWrite32b,
                 static_cast<std::uint32_t>(UCIE_LINK_DIE_RESET));
}

#endif  // TESTS_CPP_SUPPORT_UCIE_LINK_DRIVING_H_
