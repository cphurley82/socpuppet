// The one file that includes pciem's header (GPL-2.0-only, and C++23 for
// its <stdatomic.h>). See pciem_device.h.
#include "spikes/pciem/pciem_device.h"

#include <fcntl.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <span>
#include <system_error>
#include <vector>

#include "include/pciem_api.h"

namespace spike {

namespace {

[[noreturn]] void Refused(const char* what) {
  throw std::system_error(errno, std::generic_category(), what);
}

template <typename Request, typename Argument>
void Ask(int fd, Request request, Argument& argument, const char* what) {
  if (ioctl(fd, request, &argument) < 0) Refused(what);
}

std::uint64_t LowBytes(std::uint64_t data, std::uint32_t size) {
  return size >= 8 ? data : data & ((std::uint64_t{1} << (size * 8)) - 1);
}

// NVMe's class code: mass storage (01), non-volatile memory (08), NVM
// Express (02). pciem takes it lowest byte first.
constexpr std::uint8_t kNvmeClass[3] = {0x02, 0x08, 0x01};
// The MSI-X table and its pending bits go in BAR2, as pciem's NVMe
// example has them.
constexpr std::uint32_t kMsixBar = 2;
constexpr std::uint32_t kMsixBarSize = 8192;
constexpr std::uint32_t kPendingBitsAt = 4096;

}  // namespace

Drained DrainRing(void* ring_memory, std::vector<HostWrite>& writes) {
  auto* ring = static_cast<pciem_shared_ring*>(ring_memory);
  Drained drained;
  for (;;) {
    const int head = atomic_load(&ring->head);
    const int tail = atomic_load(&ring->tail);
    if (head == tail) break;
    const pciem_event& event = ring->events[head];
    if (event.type == PCIEM_EVENT_MMIO_WRITE) {
      writes.push_back({.bar = event.bar,
                        .offset = event.offset,
                        .size = event.size,
                        .data = LowBytes(event.data, event.size)});
      ++drained.writes;
    } else {
      ++drained.other_events;
    }
    atomic_store(&ring->head, (head + 1) % PCIEM_RING_SIZE);
  }
  return drained;
}

PciemDevice::PciemDevice(const Shape& shape) : bar0_size_(shape.bar0_size) {
  fd_ = open("/dev/pciem", O_RDWR | O_CLOEXEC);
  if (fd_ < 0) Refused("open /dev/pciem (is pciem.ko loaded?)");

  pciem_create_device create{};
  create.flags = PCIEM_CREATE_FLAG_BUS_MODE_VIRTUAL;
  Ask(fd_, PCIEM_IOCTL_CREATE_DEVICE, create, "CREATE_DEVICE");

  pciem_config_space config{};
  config.vendor_id = shape.vendor;
  config.device_id = shape.device;
  config.subsys_vendor_id = shape.vendor;
  config.subsys_device_id = shape.device;
  config.revision = 1;
  for (int i = 0; i < 3; ++i) config.class_code[i] = kNvmeClass[i];
  Ask(fd_, PCIEM_IOCTL_SET_CONFIG, config, "SET_CONFIG");

  pciem_bar_config bar0{};
  bar0.bar_index = 0;
  bar0.size = shape.bar0_size;
  Ask(fd_, PCIEM_IOCTL_ADD_BAR, bar0, "ADD_BAR 0");
  pciem_bar_config bar2{};
  bar2.bar_index = kMsixBar;
  bar2.size = kMsixBarSize;
  Ask(fd_, PCIEM_IOCTL_ADD_BAR, bar2, "ADD_BAR 2");

  pciem_cap_config msix{};
  msix.cap_type = PCIEM_CAP_MSIX;
  msix.msix.bar_index = kMsixBar;
  msix.msix.table_offset = 0;
  msix.msix.pba_offset = kPendingBitsAt;
  msix.msix.table_size = shape.vectors;
  Ask(fd_, PCIEM_IOCTL_ADD_CAPABILITY, msix, "ADD_CAPABILITY MSI-X");

  pciem_trace_bar trace{};
  trace.bar_index = 0;
  trace.flags = PCIEM_TRACE_WRITES;
  Ask(fd_, PCIEM_IOCTL_TRACE_BAR, trace, "TRACE_BAR 0");

  event_fd_ = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
  if (event_fd_ < 0) Refused("eventfd");
  pciem_eventfd_config events{};
  events.eventfd = event_fd_;
  Ask(fd_, PCIEM_IOCTL_SET_EVENTFD, events, "SET_EVENTFD");

  instance_fd_ = ioctl(fd_, PCIEM_IOCTL_REGISTER);
  if (instance_fd_ < 0) Refused("REGISTER");

  void* bar = mmap(nullptr, bar0_size_, PROT_READ | PROT_WRITE, MAP_SHARED,
                   instance_fd_, 0);
  if (bar == MAP_FAILED) Refused("mmap BAR0");
  bar0_ = static_cast<std::uint8_t*>(bar);
  // The memory pciem set aside at boot holds whatever was there before,
  // and the host reads every register it has not been given. Linux 7.0
  // reads the controller memory buffer's (CMBLOC, CMBSZ) and trips over
  // garbage there, so a register no one wrote reads as zero.
  std::memset(bar0_, 0, bar0_size_);
  ring_ = mmap(nullptr, sizeof(pciem_shared_ring), PROT_READ | PROT_WRITE,
               MAP_SHARED, fd_, 0);
  if (ring_ == MAP_FAILED) {
    ring_ = nullptr;
    Refused("mmap the ring");
  }
}

PciemDevice::~PciemDevice() {
  if (ring_ != nullptr) munmap(ring_, sizeof(pciem_shared_ring));
  if (bar0_ != nullptr) munmap(bar0_, bar0_size_);
  if (instance_fd_ >= 0) close(instance_fd_);
  if (event_fd_ >= 0) close(event_fd_);
  if (fd_ >= 0) close(fd_);
}

void PciemDevice::Start() {
  if (ioctl(fd_, PCIEM_IOCTL_START, 0) < 0) Refused("START");
}

Drained PciemDevice::Drain(std::vector<HostWrite>& writes) {
  std::uint64_t count = 0;
  // Nothing to read is fine: the count is cleared either way.
  [[maybe_unused]] const ssize_t got = read(event_fd_, &count, sizeof count);
  return DrainRing(ring_, writes);
}

void PciemDevice::Dma(std::uint64_t address, std::span<std::uint8_t> data,
                      bool to_host) {
  pciem_dma_op op{};
  op.guest_iova = address;
  op.user_addr = reinterpret_cast<std::uint64_t>(data.data());
  op.length = static_cast<std::uint32_t>(data.size());
  op.flags = to_host ? PCIEM_DMA_FLAG_WRITE : PCIEM_DMA_FLAG_READ;
  Ask(fd_, PCIEM_IOCTL_DMA, op, "DMA");
}

void PciemDevice::InjectIrq(unsigned vector) {
  pciem_irq_inject irq{};
  irq.vector = vector;
  Ask(fd_, PCIEM_IOCTL_INJECT_IRQ, irq, "INJECT_IRQ");
}

}  // namespace spike
