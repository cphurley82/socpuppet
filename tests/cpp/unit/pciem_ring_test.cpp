// The ring pciem posts the host's writes on, as it is drained: what of
// pciem_device.cpp can be tried with no /dev/pciem, on a ring in ordinary
// memory. C++23, as pciem's header needs, and so a program of its own,
// with no SystemC, which is built for C++20.
#include <cstdint>
#include <memory>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "include/pciem_api.h"
#include "socpuppet/core/pciem_device.h"

namespace socpuppet {

namespace {

using ::testing::ElementsAre;
using ::testing::Field;
using ::testing::IsEmpty;

pciem_event Event(std::uint32_t type, std::uint64_t offset, std::uint32_t size,
                  std::uint64_t data) {
  pciem_event event{};
  event.type = type;
  event.offset = offset;
  event.size = size;
  event.data = data;
  return event;
}

// A ring whose events start two slots before its end, so that taking them
// goes round: a write, a read of configuration space, and another write.
std::unique_ptr<pciem_shared_ring> ARingThatGoesRound() {
  auto ring = std::make_unique<pciem_shared_ring>();
  const int first = PCIEM_RING_SIZE - 2;
  atomic_store(&ring->head, first);
  ring->events[first] = Event(PCIEM_EVENT_MMIO_WRITE, 0x14, 4, 0x0046'0001);
  ring->events[first + 1] = Event(PCIEM_EVENT_CONFIG_READ, 0, 0, 0);
  ring->events[0] = Event(PCIEM_EVENT_MMIO_WRITE, 0x28, 8, 0x1'2345'6000);
  atomic_store(&ring->tail, 1);
  return ring;
}

TEST(WhenARingThatGoesRoundIsDrained,
     OnlyItsWritesAreTakenInTheOrderTheyWerePosted) {
  const auto ring = ARingThatGoesRound();

  const std::vector<HostWrite> writes = DrainRing(*ring);

  EXPECT_THAT(
      writes,
      ElementsAre(
          AllOf(Field(&HostWrite::offset, 0x14U), Field(&HostWrite::size, 4U),
                Field(&HostWrite::data, 0x0046'0001U)),
          AllOf(Field(&HostWrite::offset, 0x28U), Field(&HostWrite::size, 8U),
                Field(&HostWrite::data, 0x1'2345'6000U))));
}

TEST(WhenARingThatGoesRoundIsDrained, EverySlotIsFreedForTheKernel) {
  const auto ring = ARingThatGoesRound();

  DrainRing(*ring);

  EXPECT_EQ(atomic_load(&ring->head), atomic_load(&ring->tail));
}

TEST(WhenTheRingIsEmpty, DrainingItTakesNothing) {
  const auto ring = std::make_unique<pciem_shared_ring>();

  EXPECT_THAT(DrainRing(*ring), IsEmpty());
}

}  // namespace

}  // namespace socpuppet
