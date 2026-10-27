#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/pcie_link.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/transport.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_driver.h"
#include "tests/cpp/support/pcie_host.h"
#include "tests/cpp/support/recording_target.h"
#include "tests/cpp/support/test_components.h"

namespace socpuppet {

namespace {

// Where a function's identifiers are in its configuration space.
constexpr std::uint64_t kIds = 0x00;

// The one function behind the root complex, and one that is not there.
constexpr PciAddress kEndpoint{.bus = 0, .device = 0, .function = 0};
constexpr PciAddress kNobody{.bus = 0, .device = 1, .function = 0};

// A host with a PCIe root complex, and one endpoint behind it.
//
//   host.driver ─▶ host.bus ─┬─▶ host.memory
//                     ▲      ├─▶ host.messages
//                     │      ├─▶ host.rc (configuration window)
//                     │      └─▶ host.rc (memory window)
//                     └───────── host.rc (the device's own accesses)
//   host.rc ══ device.endpoint ─▶ device.registers
//                     ▲  ▲
//                     │  └─────── device.line (interrupt vector 1)
//                     └────────── device.function
//
// `device.registers` is a RAM standing where a function's register block
// would be, `device.function` is a test's hands on the function's DMA
// port, and `device.line` its hand on one of the function's interrupt
// lines. `host.messages` writes down every access it gets, and is where
// the tests have interrupt messages sent.
struct HostWithAnEndpoint {
  static constexpr std::uint64_t kMemoryBase = 0x8000'0000;
  static constexpr std::uint64_t kMemorySize = 0x1'0000;
  static constexpr std::uint64_t kMessagesBase = 0x2000'0000;
  static constexpr std::uint64_t kMessagesSize = 0x1000;
  // One bus's worth of configuration space: 256 functions of 4 KiB.
  static constexpr std::uint64_t kEcamBase = 0x3000'0000;
  static constexpr std::uint64_t kEcamSize = 0x10'0000;
  static constexpr std::uint64_t kWindowBase = 0x4000'0000;
  static constexpr std::uint64_t kWindowSize = 0x10'0000;
  // What the endpoint is told to say it is.
  static constexpr std::uint16_t kVendorId = 0x5350;
  static constexpr std::uint16_t kDeviceId = 0xC0DE;
  // Mass storage, non-volatile memory, NVMe: what an NVMe drive says.
  static constexpr std::uint32_t kClassCode = 0x01'08'02;
  static constexpr std::uint64_t kFunctionSize = 0x2000;
  static constexpr std::uint64_t kVectors = 2;

  // What a test has the three actors do. Each is left idle if not given.
  struct Actors {
    std::function<void(PcieHost&)> host = [](PcieHost&) {};
    // What the function does with its DMA port.
    std::function<void(BusDriver&)> function = [](BusDriver&) {};
    // And with the interrupt line of its vector 1.
    Drive line = [](LineDriver&) {};
  };

  explicit HostWithAnEndpoint(const Actors& actors)
      : platform{WithActors(actors, messages)} {
    platform.Add("host.driver", "host_driver");
    platform.Add("host.bus", "router",
                 {{"inputs", 2},
                  {"outputs", 4},
                  {"out0.base", kMemoryBase},
                  {"out0.size", kMemorySize},
                  {"out1.base", kEcamBase},
                  {"out1.size", kEcamSize},
                  {"out2.base", kWindowBase},
                  {"out2.size", kWindowSize},
                  {"out3.base", kMessagesBase},
                  {"out3.size", kMessagesSize}});
    platform.Add("host.memory", "memory", {{"size", kMemorySize}});
    platform.Add("host.messages", "recorder");
    platform.Add("host.rc", "pcie_root_complex", {{"mmio_base", kWindowBase}});
    platform.Add("device.endpoint", "pcie_endpoint",
                 {{"vendor_id", kVendorId},
                  {"device_id", kDeviceId},
                  {"class_code", kClassCode},
                  {"function_size", kFunctionSize},
                  {"vectors", kVectors}});
    platform.Add("device.registers", "memory", {{"size", kFunctionSize}});
    platform.Add("device.function", "function_driver");
    platform.Add("device.line", "line_driver");
    platform.Bind("host.driver.socket", "host.bus.target");
    platform.Bind("host.bus.out0", "host.memory.socket");
    platform.Bind("host.bus.out1", "host.rc.ecam");
    platform.Bind("host.bus.out2", "host.rc.mmio");
    platform.Bind("host.bus.out3", "host.messages.socket");
    platform.Bind("host.rc.dma", "host.bus.in1");
    platform.Bind("host.rc.to_device", "device.endpoint.from_host");
    platform.Bind("device.endpoint.to_host", "host.rc.from_device");
    platform.Bind("device.endpoint.bar0", "device.registers.socket");
    platform.Bind("device.function.socket", "device.endpoint.dma");
    platform.Bind("device.line.line", "device.endpoint.irq1");
    platform.Elaborate();
  }

  static Registry WithActors(const Actors& actors,
                             std::vector<RecordedAccess>& messages) {
    Registry registry = BuiltinComponents();
    AddBusDriver(registry, "host_driver", [host = actors.host](BusDriver& bus) {
      PcieHost pci{bus, kEcamBase};
      host(pci);
    });
    AddBusDriver(registry, "function_driver", actors.function);
    AddLineDriver(registry, "line_driver", actors.line);
    AddRecordingTarget(registry, "recorder", messages);
    return registry;
  }

  // What the RAM standing in for the function's registers holds at
  // `offset`.
  std::uint32_t FunctionRegister(std::uint64_t offset) {
    std::uint32_t value = 0;
    platform.DebugRead("device.endpoint.bar0", offset,
                       std::as_writable_bytes(std::span{&value, 1}));
    return value;
  }

  // What the host's memory holds at `address`.
  std::array<std::uint8_t, 4> HostMemory(std::uint64_t address) {
    std::array<std::uint8_t, 4> bytes{};
    platform.DebugRead("host.driver.socket", address,
                       std::as_writable_bytes(std::span{bytes}));
    return bytes;
  }

  // Puts a word in the host's memory, behind the host's back.
  void PlantInHostMemory(std::uint64_t address, std::uint32_t value) {
    platform.DebugWrite("host.driver.socket", address,
                        std::as_bytes(std::span{&value, 1}));
  }

  // What the host sees at `address` when it looks the debugger's way: in
  // no simulated time, and with nothing noticing.
  std::uint32_t HostLooksAt(std::uint64_t address) {
    return LooksAt("host.driver.socket", address);
  }

  // And what the function sees, looking the same way through its DMA port.
  std::uint32_t FunctionLooksAt(std::uint64_t address) {
    return LooksAt("device.function.socket", address);
  }

  std::uint32_t LooksAt(const char* via, std::uint64_t address) {
    std::uint32_t value = 0;
    platform.DebugRead(via, address,
                       std::as_writable_bytes(std::span{&value, 1}));
    return value;
  }

  // Every access `host.messages` has received. Declared before the
  // platform, which holds a reference to it.
  std::vector<RecordedAccess> messages;
  Platform platform;
};

// Where the tests put the endpoint's registers, and where they have its
// interrupt messages sent.
constexpr std::uint64_t kPlace = HostWithAnEndpoint::kWindowBase + 0x1'0000;
constexpr std::uint64_t kMessageAddress =
    HostWithAnEndpoint::kMessagesBase + 0x40;
constexpr std::uint32_t kMessageData = 0xCAFE'0001;
// The vector whose interrupt line the tests drive.
constexpr std::uint32_t kVector = 1;

// When the function's interrupt line rises, in the tests where it does:
// late enough for the host to have set the endpoint up first.
sc_core::sc_time LineRisesAt() { return {10, sc_core::SC_NS}; }

// When the function's DMA starts, in the tests where it does: after the
// host has made its configuration accesses at time 0, which take none.
sc_core::sc_time DmaStartsAt() { return {10, sc_core::SC_NS}; }

// What a test varies in setting vector 1 up: which bits of the command
// register the host switches on, and where the vector's messages go.
struct VectorOne {
  std::uint32_t command = PcieHost::kMemoryDecoding | PcieHost::kBusMastering;
  std::uint64_t address = kMessageAddress;
};

// What a driver does to a function before it uses its interrupts: place
// its registers, switch on what `command` says (decoding memory and
// starting accesses of its own, unless a test leaves one out), and say
// where vector 1's messages go. The vector is left masked and MSI-X off,
// for the test to switch on.
PcieHost::Msix SetUpVectorOne(PcieHost& host, VectorOne options = {}) {
  host.PlaceBar0(kEndpoint, kPlace);
  host.Command(kEndpoint, options.command);
  const PcieHost::Msix msix =
      host.FindMsix(kEndpoint).value_or(PcieHost::Msix{});
  host.SetUpVector(msix, kVector, options.address, kMessageData);
  return msix;
}

void RaiseTheLineOnce(LineDriver& line) {
  line.WaitFor(LineRisesAt());
  line.Set(true);
}

// The messages a test expects to find: one write of vector 1's data to its
// address, as many times as given.
std::vector<std::pair<std::uint64_t, std::vector<std::uint8_t>>> Messages(
    std::size_t count) {
  return {count,
          {kMessageAddress - HostWithAnEndpoint::kMessagesBase,
           {0x01, 0x00, 0xFE, 0xCA}}};
}

// What the recorder received, as (offset, bytes written) pairs.
std::vector<std::pair<std::uint64_t, std::vector<std::uint8_t>>> Received(
    const std::vector<RecordedAccess>& accesses) {
  std::vector<std::pair<std::uint64_t, std::vector<std::uint8_t>>> received;
  received.reserve(accesses.size());
  for (const RecordedAccess& access : accesses) {
    received.emplace_back(access.address, access.written);
  }
  return received;
}

// An endpoint on its own, with a test's hands at the far end of its link
// where a root complex would be.
//
//   link.host ══ device.endpoint ─▶ device.registers
//   link.up   ◀══      ▲
//                      └────────── device.function
//
// `link.host` sends what a root complex sends down the link, and `link.up`
// writes down whatever comes up it.
struct AnEndpointOnItsOwn {
  struct Actors {
    std::function<void(BusDriver&)> link = [](BusDriver&) {};
    std::function<void(BusDriver&)> function = [](BusDriver&) {};
  };

  explicit AnEndpointOnItsOwn(const Actors& actors)
      : platform{WithActors(actors, up)} {
    platform.Add("link.host", "link_driver");
    platform.Add("link.up", "recorder");
    platform.Add("device.endpoint", "pcie_endpoint",
                 {{"vendor_id", HostWithAnEndpoint::kVendorId},
                  {"device_id", HostWithAnEndpoint::kDeviceId},
                  {"class_code", HostWithAnEndpoint::kClassCode},
                  {"function_size", HostWithAnEndpoint::kFunctionSize},
                  {"vectors", HostWithAnEndpoint::kVectors}});
    platform.Add("device.registers", "memory",
                 {{"size", HostWithAnEndpoint::kFunctionSize}});
    platform.Add("device.function", "function_driver");
    platform.Bind("link.host.socket", "device.endpoint.from_host");
    platform.Bind("device.endpoint.to_host", "link.up.socket");
    platform.Bind("device.endpoint.bar0", "device.registers.socket");
    platform.Bind("device.function.socket", "device.endpoint.dma");
    platform.Elaborate();
  }

  static Registry WithActors(const Actors& actors,
                             std::vector<RecordedAccess>& up) {
    Registry registry = BuiltinComponents();
    AddBusDriver(registry, "link_driver", actors.link);
    AddBusDriver(registry, "function_driver", actors.function);
    AddRecordingTarget(registry, "recorder", up);
    return registry;
  }

  // Everything that came up the link. Declared before the platform, which
  // holds a reference to it.
  std::vector<RecordedAccess> up;
  Platform platform;
};

// A configuration write as a root complex sends it down the link: to the
// register at `offset` of the function whose bus, device and function
// numbers are `to`, as a requester ID packs them.
void ConfigurationWrite(BusDriver& link, std::uint16_t to, std::uint64_t offset,
                        std::uint32_t value) {
  std::array data = LittleEndianBytes(value);
  tlm::tlm_generic_payload transaction;
  SetUpAccess(transaction, tlm::TLM_WRITE_COMMAND, 0, data);
  const AsConfigurationAccess access{transaction, offset, to};
  sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
  link.socket->b_transport(transaction, delay);
}

}  // namespace

TEST(WhenTheHostReadsTheIdsOfAFunctionThatIsNotThere, ItGetsAllOnesAndNoError) {
  PciAccess ids;
  HostWithAnEndpoint fixture{
      {.host = [&](PcieHost& host) { ids = host.ReadConfig(kNobody, kIds); }}};

  fixture.platform.Run();

  EXPECT_EQ(ids.response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(ids.value, 0xFFFF'FFFFU);
}

TEST(WhenTheHostReadsTheIdsOfTheEndpoint, ItGetsTheVendorAndTheDevice) {
  PcieHost::Identity ids;
  HostWithAnEndpoint fixture{
      {.host = [&](PcieHost& host) { ids = host.IdsOf(kEndpoint); }}};

  fixture.platform.Run();

  EXPECT_EQ(ids.vendor, HostWithAnEndpoint::kVendorId);
  EXPECT_EQ(ids.device, HostWithAnEndpoint::kDeviceId);
}

TEST(WhenTheHostReadsTheClassOfTheEndpoint, ItGetsTheClassCodeItWasGiven) {
  std::uint32_t class_code = 0;
  HostWithAnEndpoint fixture{{.host = [&](PcieHost& host) {
    class_code = host.ClassCodeOf(kEndpoint);
  }}};

  fixture.platform.Run();

  EXPECT_EQ(class_code, HostWithAnEndpoint::kClassCode);
}

TEST(WhenTheHostLooksAtBar0, ItIsA64BitMemoryBar) {
  std::uint32_t kind = 0;
  HostWithAnEndpoint fixture{
      {.host = [&](PcieHost& host) { kind = host.KindOfBar0(kEndpoint); }}};

  fixture.platform.Run();

  EXPECT_EQ(kind, 0x4U);
}

TEST(WhenTheHostSizesBar0, ItIsAPowerOfTwoWithRoomForTheFunctionsRegisters) {
  std::uint64_t size = 0;
  HostWithAnEndpoint fixture{
      {.host = [&](PcieHost& host) { size = host.SizeOfBar0(kEndpoint); }}};

  fixture.platform.Run();

  EXPECT_TRUE(std::has_single_bit(size));
  EXPECT_GE(size, HostWithAnEndpoint::kFunctionSize);
}

TEST(WhenTheHostPlacesBar0, ItReadsBackTheAddressItChose) {
  std::uint64_t read_back = 0;
  HostWithAnEndpoint fixture{{.host = [&](PcieHost& host) {
    host.PlaceBar0(kEndpoint, kPlace);
    read_back = host.PlaceOfBar0(kEndpoint);
  }}};

  fixture.platform.Run();

  EXPECT_EQ(read_back, kPlace);
}

TEST(WhenBar0IsPlacedAndMemoryDecodingIsOn,
     AnAccessInsideItReachesTheFunctionAtItsOffset) {
  HostWithAnEndpoint fixture{{.host = [&](PcieHost& host) {
    host.PlaceBar0(kEndpoint, kPlace);
    host.Command(kEndpoint, PcieHost::kMemoryDecoding);
    host.Write(kPlace + 0x20, 0xC0FFEE);
  }}};

  fixture.platform.Run();

  EXPECT_EQ(fixture.FunctionRegister(0x20), 0xC0FFEEU);
}

TEST(WhenMemoryDecodingIsOff,
     AnAccessToWhereBar0PointsGetsAnAddressErrorAndDoesNotReachTheFunction) {
  PciAccess write;
  HostWithAnEndpoint fixture{{.host = [&](PcieHost& host) {
    host.PlaceBar0(kEndpoint, kPlace);
    write = host.Write(kPlace + 0x20, 0xC0FFEE);
  }}};

  fixture.platform.Run();

  EXPECT_EQ(write.response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(fixture.FunctionRegister(0x20), 0U);
}

TEST(WhenAnAccessInTheWindowIsOutsideBar0, ItGetsAnAddressError) {
  PciAccess read;
  HostWithAnEndpoint fixture{{.host = [&](PcieHost& host) {
    host.PlaceBar0(kEndpoint, kPlace);
    host.Command(kEndpoint, PcieHost::kMemoryDecoding);
    read = host.Read(HostWithAnEndpoint::kWindowBase);
  }}};

  fixture.platform.Run();

  EXPECT_EQ(read.response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TEST(WhenTheFunctionWritesToHostMemoryAndIsABusMaster, TheWriteLandsThere) {
  constexpr std::uint64_t kSomewhere = HostWithAnEndpoint::kMemoryBase + 0x100;
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  HostWithAnEndpoint fixture{{.host =
                                  [](PcieHost& host) {
                                    host.Command(kEndpoint,
                                                 PcieHost::kBusMastering);
                                  },
                              .function =
                                  [&](BusDriver& function) {
                                    function.WaitFor(DmaStartsAt());
                                    function.Write(kSomewhere, written);
                                  }}};

  fixture.platform.Run();

  EXPECT_EQ(fixture.HostMemory(kSomewhere), written);
}

TEST(WhenTheFunctionWritesToTheHostsBus,
     TheWriteArrivesMarkedAsFromBus0Device0Function0) {
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             host.Command(kEndpoint, PcieHost::kBusMastering);
           },
       .function =
           [](BusDriver& function) {
             function.WaitFor(DmaStartsAt());
             function.Write32(HostWithAnEndpoint::kMessagesBase, 0x1234);
           }}};

  fixture.platform.Run();

  EXPECT_THAT(fixture.messages,
              ::testing::ElementsAre(::testing::Field(
                  &RecordedAccess::requester_id, ::testing::Optional(0))));
}

TEST(WhenTheFunctionWritesToHostMemoryAndIsNotABusMaster,
     TheWriteIsRefusedAndNothingLands) {
  constexpr std::uint64_t kSomewhere = HostWithAnEndpoint::kMemoryBase + 0x100;
  const std::array<std::uint8_t, 4> written{0x11, 0x22, 0x33, 0x44};
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  HostWithAnEndpoint fixture{{.function = [&](BusDriver& function) {
    response = function.Write(kSomewhere, written);
  }}};

  fixture.platform.Run();

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
  EXPECT_EQ(fixture.HostMemory(kSomewhere),
            (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

TEST(WhenTheHostLooksAtTheFunctionsRegistersByDebugAccess,
     ItSeesThemWhereBar0WasPlaced) {
  HostWithAnEndpoint fixture{{.host = [](PcieHost& host) {
    host.PlaceBar0(kEndpoint, kPlace);
    host.Command(kEndpoint, PcieHost::kMemoryDecoding);
    host.Write(kPlace + 0x10, 0xC0FFEE);
  }}};
  fixture.platform.Run();

  EXPECT_EQ(fixture.HostLooksAt(kPlace + 0x10), 0xC0FFEEU);
}

TEST(WhenTheHostLooksAtConfigurationSpaceByDebugAccess, ItSeesTheIds) {
  HostWithAnEndpoint fixture{{}};
  fixture.platform.Run();

  EXPECT_EQ(fixture.HostLooksAt(HostWithAnEndpoint::kEcamBase + kIds),
            (std::uint32_t{HostWithAnEndpoint::kDeviceId} << 16) |
                HostWithAnEndpoint::kVendorId);
}

TEST(WhenTheFunctionLooksAtHostMemoryByDebugAccess, ItSeesIt) {
  HostWithAnEndpoint fixture{{}};
  fixture.platform.Run();
  fixture.PlantInHostMemory(HostWithAnEndpoint::kMemoryBase + 0x10, 0xC0FFEE);

  EXPECT_EQ(fixture.FunctionLooksAt(HostWithAnEndpoint::kMemoryBase + 0x10),
            0xC0FFEEU);
}

TEST(WhenTheHostWalksTheCapabilityList,
     ItFindsMsixWithOneVectorForEachInterruptLine) {
  std::optional<PcieHost::Msix> msix;
  HostWithAnEndpoint fixture{{.host = [&](PcieHost& host) {
    host.PlaceBar0(kEndpoint, kPlace);
    msix = host.FindMsix(kEndpoint);
  }}};

  fixture.platform.Run();

  EXPECT_EQ(msix.value_or(PcieHost::Msix{}).vectors,
            HostWithAnEndpoint::kVectors);
}

TEST(WhenAVectorIsSetUpAndItsInterruptLineRises,
     ItsDataIsWrittenToItsAddressOnce) {
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MaskVector(msix, kVector, false);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(1));
}

TEST(WhenAVectorIsSetUpAndItsInterruptLineRises,
     ItsMessageIsMarkedAsFromBus0Device0Function0) {
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MaskVector(msix, kVector, false);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_THAT(fixture.messages,
              ::testing::ElementsAre(::testing::Field(
                  &RecordedAccess::requester_id, ::testing::Optional(0))));
}

TEST(WhenAMessageIsSentToAnAddressNothingAnswers,
     TheStatusRegisterSaysAMasterAbortWasReceived) {
  // Outside everything on the host's bus.
  constexpr std::uint64_t kNowhere = 0x5000'0000;
  std::uint16_t status = 0;
  HostWithAnEndpoint fixture{
      {.host =
           [&](PcieHost& host) {
             const PcieHost::Msix msix =
                 SetUpVectorOne(host, {.address = kNowhere});
             host.MaskVector(msix, kVector, false);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
             // Until after the line has risen.
             host.WaitFor(2 * LineRisesAt());
             status = host.StatusOf(kEndpoint);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_TRUE(status & PcieHost::kReceivedMasterAbort);
}

TEST(WhenAnInterruptLineRisesASecondTime, ASecondMessageIsSent) {
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MaskVector(msix, kVector, false);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
           },
       .line =
           [](LineDriver& line) {
             RaiseTheLineOnce(line);
             line.WaitFor(sc_core::sc_time{10, sc_core::SC_NS});
             line.Set(false);
             line.WaitFor(sc_core::sc_time{10, sc_core::SC_NS});
             line.Set(true);
           }}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(2));
}

TEST(WhenMsixIsNotEnabled, ARisingInterruptLineSendsNothing) {
  HostWithAnEndpoint fixture{{.host =
                                  [](PcieHost& host) {
                                    const PcieHost::Msix msix =
                                        SetUpVectorOne(host);
                                    host.MaskVector(msix, kVector, false);
                                  },
                              .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(0));
}

TEST(WhenTheDeviceIsNotABusMaster, ARisingInterruptLineSendsNothing) {
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             const PcieHost::Msix msix =
                 SetUpVectorOne(host, {.command = PcieHost::kMemoryDecoding});
             host.MaskVector(msix, kVector, false);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(0));
}

TEST(WhenAVectorIsMasked, ItsRisingInterruptLineSendsNothingAndIsPending) {
  bool pending = false;
  HostWithAnEndpoint fixture{
      {.host =
           [&](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
             // Until after the line has risen.
             host.WaitFor(2 * LineRisesAt());
             pending = host.IsPending(msix, kVector);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(0));
  EXPECT_TRUE(pending);
}

TEST(WhenAPendingVectorIsUnmasked, ItsMessageIsSentAndItIsNoLongerPending) {
  bool pending = true;
  HostWithAnEndpoint fixture{
      {.host =
           [&](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
             // Until after the line has risen.
             host.WaitFor(2 * LineRisesAt());
             host.MaskVector(msix, kVector, false);
             // After the message has had time to go.
             host.WaitFor(sc_core::sc_time{10, sc_core::SC_NS});
             pending = host.IsPending(msix, kVector);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(1));
  EXPECT_FALSE(pending);
}

TEST(WhenEveryVectorIsMaskedAtOnce, ARisingInterruptLineSendsNothing) {
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MaskVector(msix, kVector, false);
             host.MsixControl(
                 kEndpoint, msix,
                 PcieHost::kMsixEnable | PcieHost::kMsixMaskEveryVector);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(0));
}

TEST(WhenTheHostWritesToThePendingBits, APendingVectorStaysPending) {
  bool pending = false;
  HostWithAnEndpoint fixture{
      {.host =
           [&](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
             // Until after the line has risen.
             host.WaitFor(2 * LineRisesAt());
             host.Write(msix.pending, 0);
             pending = host.IsPending(msix, kVector);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_TRUE(pending);
}

TEST(WhenEveryVectorIsUnmaskedAgain, AVectorThatRoseMeanwhileIsSent) {
  // A driver switches MSI-X on with every vector masked while it fills in
  // the table, and lets them all through at once when it is done. An
  // interrupt that came in between must not be lost.
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             const PcieHost::Msix msix = SetUpVectorOne(host);
             host.MaskVector(msix, kVector, false);
             host.MsixControl(
                 kEndpoint, msix,
                 PcieHost::kMsixEnable | PcieHost::kMsixMaskEveryVector);
             // Until after the line has risen.
             host.WaitFor(2 * LineRisesAt());
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(1));
}

TEST(WhenTheDeviceBecomesABusMaster, AVectorThatRoseBeforeIsSent) {
  HostWithAnEndpoint fixture{
      {.host =
           [](PcieHost& host) {
             const PcieHost::Msix msix =
                 SetUpVectorOne(host, {.command = PcieHost::kMemoryDecoding});
             host.MaskVector(msix, kVector, false);
             host.MsixControl(kEndpoint, msix, PcieHost::kMsixEnable);
             // Until after the line has risen.
             host.WaitFor(2 * LineRisesAt());
             host.Command(kEndpoint, PcieHost::kBusMastering);
           },
       .line = RaiseTheLineOnce}};

  fixture.platform.Run();

  EXPECT_EQ(Received(fixture.messages), Messages(1));
}

TEST(WhenTheEndpointIsSentAConfigurationWriteForBus2Device3Function1,
     ItsDmaIsMarkedAsFrom0x0219) {
  // Bus 2 << 8 | device 3 << 3 | function 1.
  constexpr std::uint16_t kBus2Device3Function1 = 0x0219;
  // Anywhere will do: everything that comes up the link is written down.
  constexpr std::uint64_t kAnywhere = 0x0;
  AnEndpointOnItsOwn fixture{
      {.link =
           [](BusDriver& link) {
             ConfigurationWrite(link, kBus2Device3Function1, PcieHost::kCommand,
                                PcieHost::kBusMastering);
           },
       .function =
           [](BusDriver& function) {
             function.WaitFor(DmaStartsAt());
             function.Write32(kAnywhere, 0x1234);
           }}};

  fixture.platform.Run();

  EXPECT_THAT(fixture.up, ::testing::ElementsAre(::testing::Field(
                              &RecordedAccess::requester_id,
                              ::testing::Optional(kBus2Device3Function1))));
}

}  // namespace socpuppet
