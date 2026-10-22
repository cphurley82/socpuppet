// The ring, on a ring in ordinary memory: what of pciem_device.cpp can be
// tried with no /dev/pciem. C++23, as pciem's header needs, and so with no
// SystemC, which is built for C++20.
#include <cstdint>
#include <memory>
#include <vector>

#include <gtest/gtest.h>

#include "include/pciem_api.h"
#include "spikes/pciem/pciem_device.h"

namespace {

pciem_event Event(std::uint32_t type, std::uint64_t offset, std::uint32_t size,
                  std::uint64_t data) {
  pciem_event event{};
  event.type = type;
  event.offset = offset;
  event.size = size;
  event.data = data;
  return event;
}

TEST(DrainRing, TakesTheWritesKeepsTheirSizeAndFreesEverySlot) {
  auto ring = std::make_unique<pciem_shared_ring>();
  // Two slots before the end, so that the drain wraps.
  const int first = PCIEM_RING_SIZE - 2;
  atomic_store(&ring->head, first);
  ring->events[first] =
      Event(PCIEM_EVENT_MMIO_WRITE, 0x14, 4, 0xdead'beef'0046'0001);
  ring->events[first + 1] = Event(PCIEM_EVENT_CONFIG_READ, 0, 0, 0);
  ring->events[0] = Event(PCIEM_EVENT_MMIO_WRITE, 0x28, 8, 0x1'2345'6000);
  atomic_store(&ring->tail, 1);

  std::vector<spike::HostWrite> writes;
  const spike::Drained drained = spike::DrainRing(ring.get(), writes);

  EXPECT_EQ(drained.writes, 2U);
  EXPECT_EQ(drained.other_events, 1U);
  ASSERT_EQ(writes.size(), 2U);
  EXPECT_EQ(writes[0].data, 0x0046'0001U);  // only its four bytes
  EXPECT_EQ(writes[1].data, 0x1'2345'6000U);
  EXPECT_EQ(atomic_load(&ring->head), 1);
}

}  // namespace
