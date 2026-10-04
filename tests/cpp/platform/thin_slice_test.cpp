#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/models/scripted_bus_master.h"

TEST(WhenAMasterWritesAWordThroughThePassThroughLink, TheMemoryHoldsIt) {
  socpuppet::ScriptedBusMaster master{"master", {socpuppet::Write32{0x10, 0xC0FFEE}}};
  socpuppet::PassThroughLink link{"link"};
  socpuppet::Memory memory{"memory", 0x100};
  master.socket.bind(link.target);
  link.initiator.bind(memory.socket);

  sc_core::sc_start();  // run until the master has played all its ops

  EXPECT_EQ(memory.peek32(0x10), 0xC0FFEEu);
}
