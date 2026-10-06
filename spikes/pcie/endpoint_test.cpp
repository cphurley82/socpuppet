// What the VCML-backed endpoint does, question by question (see
// docs/pcie-spike.md). Each test builds a platform of its own, so each runs
// in a process of its own: `ctest` does that.
#include <array>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <numeric>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#ifdef __APPLE__
#include <pthread.h>

#include <mach/mach.h>
#endif

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "spikes/pcie/rig.h"
#include "tests/cpp/support/nvme_host.h"

namespace {

using spike::kBar0;
using spike::kBar1;
using spike::kBusMasterEnable;
using spike::kCommand;
using spike::kMemoryBase;
using spike::kMemoryEnable;
using spike::kMsiBase;
using spike::kMsixCapability;
using spike::kVectors;
using spike::PciHost;
using spike::Seen;
using spike::StandInRig;
using ::testing::ElementsAre;
using ::testing::Field;
using ::testing::IsEmpty;
using ::testing::SizeIs;

// A message for vector `data`, as the catcher sees it: one four-byte write
// at the start of its page.
auto Message(std::uint32_t data) {
  return ::testing::AllOf(
      Field("command", &Seen::command, tlm::TLM_WRITE_COMMAND),
      Field("address", &Seen::address, 0U), Field("length", &Seen::length, 4U),
      Field("word", &Seen::word, data));
}

void Raise(sc_core::sc_out<bool>& line, PciHost& host) {
  line.write(true);
  host.Wait();
}
void Lower(sc_core::sc_out<bool>& line, PciHost& host) {
  line.write(false);
  host.Wait();
}

// ---- (a) configuration space through ECAM ---------------------------------

TEST(ConfigurationSpace, HasTheIdsAndClassCodeItWasGiven) {
  StandInRig rig;
  rig.OnTheHost([](BusDriver& bus) {
    PciHost host{bus};
    EXPECT_EQ(host.Config<std::uint16_t>(spike::kIds), spike::kVendorId);
    EXPECT_EQ(host.Config<std::uint16_t>(spike::kIds + 2), spike::kDeviceId);
    EXPECT_EQ(host.Config(spike::kIds),
              std::uint32_t{spike::kDeviceId} << 16 | spike::kVendorId);
    // Class code in the top three bytes, revision in the lowest.
    EXPECT_EQ(host.Config(spike::kClassAndRevision) >> 8,
              spike::kNvmeClassCode);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);
    // Header type 0: an endpoint, with one function.
    EXPECT_EQ(host.Config<std::uint8_t>(0x0E), 0);
  });
}

TEST(ConfigurationSpace, AFunctionThatIsNotThereReadsAllOnes) {
  StandInRig rig;
  rig.OnTheHost([](BusDriver& bus) {
    PciHost host{bus};
    for (const std::uint64_t absent :
         {PciHost::Ecam(0, 1, 0, 0), PciHost::Ecam(0, 0, 1, 0),
          PciHost::Ecam(1, 0, 0, 0), PciHost::Ecam(255, 31, 7, 0)}) {
      EXPECT_EQ(host.Read(absent), 0xFFFF'FFFFU) << std::hex << absent;
      EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);
    }
    // A register the function does not have reads as zero, not an error.
    EXPECT_EQ(host.Config(0xF00), 0U);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);
  });
}

// ---- (b) BAR0 ---------------------------------------------------------------

TEST(Bar0, IsSizedAndPlacedTheWayZephyrDoesIt) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    // Out of reset: a 64-bit memory BAR, not prefetchable, at address 0.
    EXPECT_EQ(host.Config(kBar0), 0x4U);
    EXPECT_EQ(host.Config(kBar1), 0U);
    // The function's 0x2000 bytes, then the MSI-X table: 0x4000 in all.
    EXPECT_EQ(host.SizeOfBar0(), 0x4000U);

    const std::uint64_t bar0 = host.PlaceBar0(0x0120'0000);
    EXPECT_EQ(host.Config(kBar0), 0x0120'0004U);
    host.SetConfig<std::uint16_t>(kCommand, kMemoryEnable);

    host.Write<std::uint32_t>(bar0 + 0x1004, 0xC0FFEE);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);
    EXPECT_EQ(host.Read<std::uint32_t>(bar0 + 0x1004), 0xC0FFEEU);
    // An NVMe driver reads and writes 64-bit registers in one access.
    host.Write<std::uint64_t>(bar0 + 0x28, 0x1122'3344'5566'7788);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);
    EXPECT_THAT(
        rig.Function().accesses,
        ElementsAre(Field("address", &Seen::address, 0x1004U),
                    Field("address", &Seen::address, 0x1004U),
                    ::testing::AllOf(Field("address", &Seen::address, 0x28U),
                                     Field("length", &Seen::length, 8U))));
  });
}

TEST(Bar0, ReachesNothingWhileMemoryDecodingIsOff) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t bar0 = host.PlaceBar0(0x0120'0000);
    // Placed, but the command register's memory-enable bit is still clear.
    host.Read<std::uint32_t>(bar0);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_ADDRESS_ERROR_RESPONSE);

    host.SetConfig<std::uint16_t>(kCommand, kMemoryEnable);
    host.Read<std::uint32_t>(bar0);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);

    host.SetConfig<std::uint16_t>(kCommand, 0);
    host.Read<std::uint32_t>(bar0);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_ADDRESS_ERROR_RESPONSE);
    EXPECT_THAT(rig.Function().accesses, SizeIs(1));
  });
}

TEST(Bar0, TakesNoAccessLargerThanEightBytes) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t bar0 = host.BringUp();
    std::array<std::uint8_t, 16> sixteen{};
    EXPECT_EQ(bus.Read(bar0, sixteen), tlm::TLM_COMMAND_ERROR_RESPONSE);
    EXPECT_THAT(rig.Function().accesses, IsEmpty());
  });
}

// ---- (c) the function's DMA -------------------------------------------------

TEST(Dma, AWholePageIsOneTransaction) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    std::vector<std::uint8_t> page(4096);
    std::iota(page.begin(), page.end(), std::uint8_t{1});
    for (int time = 0; time < 2; ++time) {
      EXPECT_EQ(rig.Function().DmaWrite(kMemoryBase + 0x3000, page),
                tlm::TLM_OK_RESPONSE);
    }
    std::vector<std::uint8_t> landed(4096);
    bus.Read(kMemoryBase + 0x3000, landed);
    EXPECT_EQ(landed, page);
    std::vector<std::uint8_t> back(4096);
    EXPECT_EQ(rig.Function().DmaRead(kMemoryBase + 0x3000, back),
              tlm::TLM_OK_RESPONSE);
    EXPECT_EQ(back, page);

    const auto whole_page_at = [](tlm::tlm_command command) {
      return ::testing::AllOf(
          Field("command", &Seen::command, command),
          Field("address", &Seen::address, kMemoryBase + 0x3000),
          Field("length", &Seen::length, 4096U));
    };
    EXPECT_THAT(rig.DmaSpy().seen,
                ElementsAre(whole_page_at(tlm::TLM_WRITE_COMMAND),
                            whole_page_at(tlm::TLM_WRITE_COMMAND),
                            whole_page_at(tlm::TLM_READ_COMMAND)));
    EXPECT_EQ(rig.DmaSpy().direct_memory_requests, 0);
    // It goes out in the thread that asked, here the test's own, and the
    // data is the function's buffer, not a copy of it.
    EXPECT_EQ(rig.DmaSpy().seen.front().process, "host.driver.Run");
    EXPECT_EQ(rig.DmaSpy().seen.front().data, page.data());
  });
}

#ifndef SPIKE_BARE_ENDPOINT
// What VCML does when left alone: after the first transaction it asks the
// memory for direct access and the bus never sees its DMA again.
TEST(Dma, WithDirectMemoryAllowedOnlyTheFirstPageIsATransaction) {
  StandInRig rig{{{"dma_by_dmi", 1}}};
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    std::vector<std::uint8_t> page(4096, 0x5A);
    for (int time = 0; time < 3; ++time) {
      page[0] = static_cast<std::uint8_t>(time);
      EXPECT_EQ(rig.Function().DmaWrite(kMemoryBase + 0x3000, page),
                tlm::TLM_OK_RESPONSE);
    }
    std::vector<std::uint8_t> landed(4096);
    bus.Read(kMemoryBase + 0x3000, landed);
    EXPECT_EQ(landed, page);
    EXPECT_THAT(rig.DmaSpy().seen, SizeIs(1));
    EXPECT_EQ(rig.DmaSpy().direct_memory_requests, 1);
  });
}
#endif  // SPIKE_BARE_ENDPOINT

TEST(Dma, IsNotHeldBackByBusMasterEnable) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    // Nothing enabled at all: a real endpoint may not start a transaction.
    std::vector<std::uint8_t> page(4096, 0x77);
    EXPECT_EQ(rig.Function().DmaWrite(kMemoryBase, page), tlm::TLM_OK_RESPONSE);
    EXPECT_THAT(rig.DmaSpy().seen, SizeIs(1));
  });
}

// ---- (d) MSI-X
// ----------------------------------------------------------------

TEST(Msix, IsFoundByWalkingTheCapabilityList) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    std::vector<unsigned> ids;
    for (unsigned at = host.Config<std::uint8_t>(spike::kCapabilitiesPointer);
         at != 0; at = host.Config<std::uint8_t>(at + 1)) {
      ids.push_back(host.Config<std::uint8_t>(at));
    }
    // MSI-X, then the two VCML gives every PCIe device: power management
    // and PCI Express.
    EXPECT_THAT(ids, ElementsAre(0x11, 0x01, 0x10));

    const unsigned msix = host.FindCapability(kMsixCapability);
    ASSERT_NE(msix, 0U);
    const auto control =
        host.Config<std::uint16_t>(msix + spike::kMessageControl);
    EXPECT_EQ((control & 0x7FFU) + 1, kVectors);
    EXPECT_EQ(control & (spike::kMsixEnable | spike::kFunctionMask), 0);
    // Both in BAR0 (the low three bits), after the function's registers.
    EXPECT_EQ(host.Config(msix + spike::kTableOffset), 0x2000U);
    EXPECT_EQ(host.Config(msix + spike::kPendingOffset),
              0x2000U + (16 * kVectors));
  });
}

TEST(Msix, TableIsReadAndWrittenThroughBar0) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t bar0 = host.PlaceBar0(0x10'0000);
    host.SetConfig<std::uint16_t>(kCommand, kMemoryEnable);
    const std::uint64_t entry2 = bar0 + 0x2000 + (16 * 2);
    // Out of reset every vector is masked.
    EXPECT_EQ(host.Read(entry2 + 12), 1U);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);
    host.SetVector(bar0 + 0x2000, 2, 0x1'2345'6780, 0xABCD, false);
    EXPECT_EQ(host.LastStatus(), tlm::TLM_OK_RESPONSE);
    EXPECT_EQ(host.Read(entry2), 0x2345'6780U);
    EXPECT_EQ(host.Read(entry2 + 4), 0x1U);
    EXPECT_EQ(host.Read(entry2 + 8), 0xABCDU);
    EXPECT_EQ(host.Read(entry2 + 12), 0U);
    // None of it was the function's business.
    EXPECT_THAT(rig.Function().accesses, IsEmpty());
  });
}

TEST(Msix, EachRiseOfALineIsOneMessage) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    auto& irq = rig.Function().irq;

    Raise(irq[1], host);
    EXPECT_THAT(rig.Msi().messages, ElementsAre(Message(1)));
    // Staying high says nothing more.
    host.Wait({1, sc_core::SC_MS});
    EXPECT_THAT(rig.Msi().messages, SizeIs(1));

    Lower(irq[1], host);
    Raise(irq[1], host);
    Raise(irq[3], host);
    EXPECT_THAT(rig.Msi().messages,
                ElementsAre(Message(1), Message(1), Message(3)));

    // (e) Every one left the endpoint as one four-byte write, from a thread
    // of VCML's.
    ASSERT_THAT(rig.DmaSpy().seen, SizeIs(3));
    for (const Seen& sent : rig.DmaSpy().seen) {
      EXPECT_EQ(sent.address, kMsiBase);
      EXPECT_EQ(sent.length, 4U);
      EXPECT_TRUE(sent.from_thread);
      EXPECT_THAT(sent.process, ::testing::EndsWith("endpoint.msix_process"));
    }
  });
}

TEST(Msix, ARiseAndFallInOneDeltaCycleIsStillAMessage) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    auto& irq = rig.Function().irq;
    irq[2].write(true);
    bus.WaitFor(sc_core::SC_ZERO_TIME);
    irq[2].write(false);
    host.Wait();
    std::printf("[measured] a one-delta pulse gave %zu message(s)\n",
                rig.Msi().messages.size());
  });
}

TEST(Msix, AMaskedVectorWaitsUntilItIsUnmasked) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t bar0 = host.BringUp();
    const std::uint64_t table = bar0 + 0x2000;
    const std::uint64_t pending = table + (16 * kVectors);
    auto& irq = rig.Function().irq;

    host.SetVector(table, 2, kMsiBase, 2, /*masked=*/true);
    Raise(irq[2], host);
    EXPECT_THAT(rig.Msi().messages, IsEmpty());
    EXPECT_EQ(host.Read(pending), 1U << 2);

    host.SetVector(table, 2, kMsiBase, 2, /*masked=*/false);
    host.Wait();
    EXPECT_THAT(rig.Msi().messages, ElementsAre(Message(2)));
    EXPECT_EQ(host.Read(pending), 0U);
  });
}

TEST(Msix, TheFunctionMaskHoldsEveryVectorBack) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    const unsigned control =
        host.FindCapability(kMsixCapability) + spike::kMessageControl;
    auto& irq = rig.Function().irq;

    host.SetConfig<std::uint16_t>(control,
                                  spike::kMsixEnable | spike::kFunctionMask);
    Raise(irq[0], host);
    Raise(irq[3], host);
    EXPECT_THAT(rig.Msi().messages, IsEmpty());

    host.SetConfig<std::uint16_t>(control, spike::kMsixEnable);
    host.Wait();
    EXPECT_THAT(rig.Msi().messages, ElementsAre(Message(0), Message(3)));
  });
}

// The specification lets a function forget a masked interrupt whose cause
// has gone away, and VCML does.
TEST(Msix, AMaskedVectorWhoseLineFellAgainIsForgotten) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t table = host.BringUp() + 0x2000;
    auto& irq = rig.Function().irq;
    host.SetVector(table, 2, kMsiBase, 2, /*masked=*/true);
    Raise(irq[2], host);
    Lower(irq[2], host);
    host.SetVector(table, 2, kMsiBase, 2, /*masked=*/false);
    host.Wait();
    EXPECT_THAT(rig.Msi().messages, IsEmpty());
  });
}

TEST(Msix, SendsNothingWhileItIsDisabled) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    const unsigned control =
        host.FindCapability(kMsixCapability) + spike::kMessageControl;
    host.SetConfig<std::uint16_t>(control, 0);
    auto& irq = rig.Function().irq;
    Raise(irq[1], host);
    EXPECT_THAT(rig.Msi().messages, IsEmpty());
    // And the rise is not remembered for later.
    host.SetConfig<std::uint16_t>(control, spike::kMsixEnable);
    host.Wait();
    EXPECT_THAT(rig.Msi().messages, IsEmpty());
    EXPECT_THAT(rig.DmaSpy().seen, IsEmpty());
  });
}

// A real endpoint may not send a message while bus mastering is off. VCML
// asks for memory decoding instead.
TEST(Msix, IsGatedByMemoryEnableAndNotByBusMasterEnable) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    auto& irq = rig.Function().irq;

    host.SetConfig<std::uint16_t>(kCommand, kMemoryEnable);
    Raise(irq[0], host);
    EXPECT_THAT(rig.Msi().messages, ElementsAre(Message(0)));

    host.SetConfig<std::uint16_t>(kCommand, kBusMasterEnable);
    Raise(irq[1], host);
    EXPECT_THAT(rig.Msi().messages, SizeIs(1));
  });
}

// ---- (e) who waits
// ------------------------------------------------------------

// One access by a master that has run `lead` ahead of the clock, and what
// became of the clock and of the lead.
struct Timed {
  sc_core::sc_time clock_moved;
  sc_core::sc_time lead_after;
  sc_dt::uint64 delta_cycles;
};

Timed Access(BusDriver& bus, tlm::tlm_command command, std::uint64_t address,
             unsigned length, const sc_core::sc_time& lead) {
  std::array<std::uint8_t, 8> data{};
  tlm::tlm_generic_payload transaction;
  transaction.set_command(command);
  transaction.set_address(address);
  transaction.set_data_ptr(data.data());
  transaction.set_data_length(length);
  transaction.set_streaming_width(length);
  sc_core::sc_time delay = lead;
  const sc_core::sc_time before = sc_core::sc_time_stamp();
  const sc_dt::uint64 deltas = sc_core::sc_delta_count();
  bus.socket->b_transport(transaction, delay);
  EXPECT_EQ(transaction.get_response_status(), tlm::TLM_OK_RESPONSE);
  return {.clock_moved = sc_core::sc_time_stamp() - before,
          .lead_after = delay,
          .delta_cycles = sc_core::sc_delta_count() - deltas};
}

void Print(const char* what, const Timed& timed) {
  std::printf("[measured] %-46s clock moved %-6s lead now %-6s deltas %s\n",
              what, timed.clock_moved.to_string().c_str(),
              timed.lead_after.to_string().c_str(),
              std::to_string(timed.delta_cycles).c_str());
}

// Not a pass-or-fail test: it prints what VCML does with time inside
// b_transport, for the report.
void MeasureWaits(const sc_core::sc_time& quantum) {
  StandInRig rig;
  rig.Platform().SetQuantum(quantum);
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t bar0 = host.BringUp();
    const sc_core::sc_time lead{5, sc_core::SC_NS};
    const sc_core::sc_time none = sc_core::SC_ZERO_TIME;
    std::printf("[measured] global quantum %s\n", quantum.to_string().c_str());
    Print(
        "config read (vendor id), no lead",
        Access(bus, tlm::TLM_READ_COMMAND, PciHost::Ecam(0, 0, 0, 0), 4, none));
    Print(
        "config read (vendor id), lead 5 ns",
        Access(bus, tlm::TLM_READ_COMMAND, PciHost::Ecam(0, 0, 0, 0), 4, lead));
    Print(
        "config read (command), lead 5 ns",
        Access(bus, tlm::TLM_READ_COMMAND, PciHost::Ecam(0, 0, 0, 4), 2, lead));
    Print(
        "config read of an absent function, lead 5 ns",
        Access(bus, tlm::TLM_READ_COMMAND, PciHost::Ecam(0, 3, 0, 0), 4, lead));
    Print("BAR0 read into the function, no lead",
          Access(bus, tlm::TLM_READ_COMMAND, bar0, 4, none));
    Print("BAR0 read into the function, lead 5 ns",
          Access(bus, tlm::TLM_READ_COMMAND, bar0, 4, lead));
    Print("MSI-X table read, lead 5 ns",
          Access(bus, tlm::TLM_READ_COMMAND, bar0 + 0x2000, 4, lead));
    const sc_core::sc_time far{2, sc_core::SC_US};
    Print(
        "config read (command), lead 2 us",
        Access(bus, tlm::TLM_READ_COMMAND, PciHost::Ecam(0, 0, 0, 4), 2, far));
    Print("BAR0 read into the function, lead 2 us",
          Access(bus, tlm::TLM_READ_COMMAND, bar0, 4, far));
    for (const Seen& access : rig.Function().accesses) {
      std::printf("[measured] the function saw a lead of %s\n",
                  access.lead.to_string().c_str());
    }
    rig.Function().access_time = {7, sc_core::SC_NS};
    Print("BAR0 read that the function says takes 7 ns",
          Access(bus, tlm::TLM_READ_COMMAND, bar0, 4, lead));
  });
}

TEST(Waiting, InsideBTransportWithNoQuantum) {
  MeasureWaits(sc_core::SC_ZERO_TIME);
}
TEST(Waiting, InsideBTransportWithAQuantumOfAMicrosecond) {
  MeasureWaits({1, sc_core::SC_US});
}

// ---- process-wide behaviour
// ---------------------------------------------------

TEST(Kernel, AnUnboundedRunReturnsWhenNothingIsLeftToDo) {
  StandInRig rig;
  bool finished = false;
  rig.OnTheHostUntilNothingIsLeft([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    Raise(rig.Function().irq[0], host);
    finished = true;
  });
  EXPECT_TRUE(finished);
  EXPECT_THAT(rig.Msi().messages, SizeIs(1));
}

TEST(Kernel, MayRunOnAThreadOtherThanTheOneThatLoadedVcml) {
  bool finished = false;
  std::thread kernel{[&] {
    StandInRig rig;
    rig.OnTheHost([&](BusDriver& bus) {
      PciHost host{bus};
      host.BringUp();
      finished = true;
    });
  }};
  kernel.join();
  EXPECT_TRUE(finished);
}

// How many threads this process has, with their names printed. (macOS
// only: the spike's machine.)
int Threads(const char* when) {
#ifdef __APPLE__
  thread_act_array_t threads = nullptr;
  mach_msg_type_number_t count = 0;
  task_threads(mach_task_self(), &threads, &count);
  std::printf("[measured] threads %s: %u", when, count);
  for (mach_msg_type_number_t each = 0; each < count; ++each) {
    std::array<char, 64> name{};
    if (pthread_t thread = pthread_from_mach_thread_np(threads[each])) {
      pthread_getname_np(thread, name.data(), name.size());
    }
    std::printf(" \"%s\"", name.data());
  }
  std::printf("\n");
  return static_cast<int>(count);
#else
  (void)when;
  return -1;
#endif
}

// Taken while the program's static objects are being built, VCML's among
// them, and before main() has set up socpuppet's logging.
const int threads_before_main = Threads("before main()");

TEST(Kernel, VcmlInstallsNoSignalHandlersAndStartsNoThreads) {
  // One more than before main(): the worker of socpuppet's own logging.
  const int threads_before = Threads("before the platform is built");
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    host.BringUp();
    Raise(rig.Function().irq[0], host);
  });
  std::vector<int> handled;
  for (int signal = 1; signal < NSIG; ++signal) {
    struct sigaction action{};
    if (sigaction(signal, nullptr, &action) == 0 &&
        action.sa_handler != SIG_DFL) {
      handled.push_back(signal);
    }
  }
  EXPECT_THAT(handled, IsEmpty());
  EXPECT_EQ(Threads("after the run"), threads_before);
}

// A debugger's view (debug transport) goes through as well, with no
// process running at all.
TEST(Kernel, DebugTransportReachesConfigurationSpaceAndTheFunction) {
  StandInRig rig;
  std::uint64_t bar0 = 0;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    bar0 = host.BringUp();
  });
  std::array<std::byte, 4> ids{};
  EXPECT_TRUE(rig.Platform().DebugRead("host.driver.socket",
                                       PciHost::Ecam(0, 0, 0, 0), ids));
  EXPECT_EQ(std::to_integer<unsigned>(ids[0]), spike::kVendorId & 0xFFU);
  // The stand-in function does not answer debug accesses, and neither does
  // the behavioral NVMe function, so there is nothing to read. Getting
  // "no" for an answer is the point: see the same access in as_is_test.cpp.
  std::array<std::byte, 4> word{};
  EXPECT_FALSE(rig.Platform().DebugRead("host.driver.socket", bar0, word));
  // The MSI-X table is the endpoint's own, and can be looked at.
  EXPECT_TRUE(
      rig.Platform().DebugRead("host.driver.socket", bar0 + 0x2000 + 8, word));
  EXPECT_EQ(std::to_integer<unsigned>(word[0]), 0U);  // vector 0's data
}

// VCML checks what it is handed, and when a check fails it prints a
// backtrace and calls abort(). These are two ways a neighbour can trip one.
using VcmlDeathTest = ::testing::Test;

// (Only where VCML's host is the one receiving: the adapter that plays the
// host itself does not mind.)
#ifndef SPIKE_BARE_ENDPOINT
TEST(VcmlDeathTest, APayloadSentTwiceWithoutResettingItsResponseAborts) {
  GTEST_FLAG_SET(death_test_style, "threadsafe");
  EXPECT_DEATH(
      {
        StandInRig rig;
        rig.OnTheHost([&](BusDriver& bus) {
          std::array<std::uint8_t, 4> data{};
          tlm::tlm_generic_payload transaction;
          transaction.set_command(tlm::TLM_READ_COMMAND);
          transaction.set_address(PciHost::Ecam(0, 0, 0, 0));
          transaction.set_data_ptr(data.data());
          transaction.set_data_length(4);
          transaction.set_streaming_width(4);
          sc_core::sc_time delay;
          bus.socket->b_transport(transaction, delay);
          // The second time it still says TLM_OK_RESPONSE. (The address
          // is set again because the router changed it.)
          transaction.set_address(PciHost::Ecam(0, 0, 0, 0));
          bus.socket->b_transport(transaction, delay);
        });
      },
      "invalid in-bound transaction response status");
}
#endif  // SPIKE_BARE_ENDPOINT

TEST(VcmlDeathTest, DmaFromAMethodProcessAborts) {
  GTEST_FLAG_SET(death_test_style, "threadsafe");
  EXPECT_DEATH(
      {
        StandInRig rig;
        // A method process that does one DMA write when the run starts.
        sc_core::sc_spawn_options method;
        method.spawn_method();
        sc_core::sc_spawn(
            [&] {
              const std::array<std::uint8_t, 4> data{};
              rig.Function().DmaWrite(kMemoryBase, data);
            },
            "dma_from_a_method", &method);
        rig.OnTheHost(
            [&](BusDriver& bus) { bus.WaitFor({1, sc_core::SC_NS}); });
      },
      "outside SC_THREAD");
}

// A message to an address nobody answers at. VCML logs a warning about it:
// the test is here to show where that warning goes.
TEST(Kernel, AMessageNobodyAnswersIsOnlyAWarningOfVcmls) {
  StandInRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost host{bus};
    const std::uint64_t table = host.BringUp() + 0x2000;
    host.SetVector(table, 0, 0x7000'0000, 0, /*masked=*/false);
    Raise(rig.Function().irq[0], host);
    EXPECT_THAT(rig.Msi().messages, IsEmpty());
    EXPECT_THAT(rig.DmaSpy().seen, SizeIs(1));
  });
}

// ---- (f) the whole path
// ---------------------------------------------------------

// The behavioral NVMe function behind the endpoint, and a line watcher on
// each of the catcher's lines, so that the tests' NVMe host can wait for an
// interrupt as it does without PCIe.
class NvmeRig : public spike::Rig {
 public:
  NvmeRig() {
    Platform().Add("nvme", "behavioral_nvme",
                   {{"blocks", 64}, {"vectors", kVectors}});
    Platform().Bind("pcie.bar0", "nvme.bar0");
    Platform().Bind("nvme.dma", "pcie.function_dma");
    for (std::size_t vector = 0; vector < kVectors; ++vector) {
      const std::string number = std::to_string(vector);
      Platform().Bind("nvme.irq" + number, "pcie.irq" + number);
      Platform().Add("host.irq" + number, "line_watcher");
      Platform().Bind("host.msi.line" + number, "host.irq" + number + ".line");
    }
  }

  std::vector<LineWatcher*> InterruptLines() {
    std::vector<LineWatcher*> lines;
    for (std::size_t vector = 0; vector < kVectors; ++vector) {
      lines.push_back(&Platform().ModuleAt<LineWatcher>(
          "host.irq" + std::to_string(vector)));
    }
    return lines;
  }
};

TEST(Nvme, IdentifyCompletesAndItsInterruptArrivesAsAnMsixMessage) {
  NvmeRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost pci{bus};
    const std::uint64_t bar0 = pci.BringUp();

    NvmeHost host{bus, bar0, kMemoryBase, rig.InterruptLines()};
    host.Enable();
    EXPECT_TRUE(host.IsReady());
    EXPECT_EQ(host.NumberOfNamespaces(), 1U);
    EXPECT_TRUE(host.WaitForInterrupts(0, 1));
    EXPECT_THAT(rig.Msi().messages, ElementsAre(Message(0)));

    // A second command, a second message.
    const auto name_space = host.IdentifyNamespace(1);
    ASSERT_TRUE(name_space.has_value());
    EXPECT_EQ(name_space->blocks, 64U);
    EXPECT_TRUE(host.WaitForInterrupts(0, 2));
    EXPECT_THAT(rig.Msi().messages, ElementsAre(Message(0), Message(0)));
  });
}

TEST(Nvme, BlocksWrittenThroughTheEndpointReadBack) {
  NvmeRig rig;
  rig.OnTheHost([&](BusDriver& bus) {
    PciHost pci{bus};
    NvmeHost host{bus, pci.BringUp(), kMemoryBase, rig.InterruptLines()};
    host.Enable();
    ASSERT_TRUE(host.CreateIoQueues(/*vector=*/1));
    std::vector<std::uint8_t> data(3 * 4096);
    std::iota(data.begin(), data.end(), std::uint8_t{3});
    const auto written = host.WriteBlocks(8, data);
    ASSERT_TRUE(written.has_value());
    EXPECT_EQ(written->status, 0);
    EXPECT_EQ(host.ReadBlocks(8, 24), data);
    EXPECT_TRUE(host.WaitForInterrupts(1, 2));
  });
}

}  // namespace
