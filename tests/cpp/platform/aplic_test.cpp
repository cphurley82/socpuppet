#include "socpuppet/models/aplic.h"

#include <cstdint>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/recording_target.h"

// What is the Aplic's alone. What every APLIC must do is in the APLIC
// contract (tests/cpp/contracts/aplic_contract.h).

// The borrowed model has every source the register map has room for, and
// each of its inputs that the adapter does not bring out is tied low. A
// source set up to ask while its line is low would then be asking for
// ever. So a source the Aplic does not have cannot be set up at all.
TEST(WhenASourceBeyondTheAplicsLastIsSetUpToAskWhileItsLineIsLow,
     ItStaysInactiveAndSendsNothing) {
  constexpr std::uint32_t kBeyondTheLast = socpuppet::Aplic::kSources + 1;
  constexpr std::uint64_t kItsMode = std::uint64_t{4} * kBeyondTheLast;
  constexpr std::uint64_t kItsTarget = 0x3000 + kItsMode;
  constexpr std::uint32_t kLevelLow = 7;
  socpuppet::Aplic aplic{"aplic"};
  std::vector<RecordedAccess> messages;
  RecordingTarget harts_page{"harts_page", messages, sc_core::SC_ZERO_TIME};
  aplic.msi.bind(harts_page.socket);
  std::uint32_t mode = kLevelLow;
  BusDriver driver{"driver", [&](BusDriver& bus) {
                     bus.Write32(0x1BC0, 0x24000);  // where messages go
                     bus.Write32(0x0000, 1U << 8);  // interrupts on
                     bus.Write32(kItsMode, kLevelLow);
                     bus.Write32(kItsTarget, 40);
                     bus.Write32(0x1EDC, kBeyondTheLast);  // enable it
                     mode = bus.Read32(kItsMode);
                     bus.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
                   }};
  driver.socket.bind(aplic.socket);

  sc_core::sc_start();

  EXPECT_EQ(mode, 0U);
  EXPECT_TRUE(messages.empty());
}

// The row of modes ends with room for a source the borrowed model has no
// input for, and the model would look for one.
TEST(WhenTheLastModeTheRegisterMapHasRoomForIsWritten, NothingHappens) {
  constexpr std::uint64_t kLastMode = 0x0FFC;
  socpuppet::Aplic aplic{"aplic"};
  std::vector<RecordedAccess> messages;
  RecordingTarget harts_page{"harts_page", messages, sc_core::SC_ZERO_TIME};
  aplic.msi.bind(harts_page.socket);
  tlm::tlm_response_status answer = tlm::TLM_INCOMPLETE_RESPONSE;
  BusDriver driver{"driver",
                   [&](BusDriver& bus) { answer = bus.Write32(kLastMode, 6); }};
  driver.socket.bind(aplic.socket);

  sc_core::sc_start();

  EXPECT_EQ(answer, tlm::TLM_OK_RESPONSE);
  EXPECT_TRUE(messages.empty());
}
