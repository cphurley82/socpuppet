// 🐧 The calls to /dev/pciem. The one source file that includes pciem's
// header, which is GPL-2.0-only and needs C++23 for its <stdatomic.h>, so
// it is built in a library of its own, with no SystemC (pciem_device.h).
#include "socpuppet/core/pciem_device.h"

#include <fcntl.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <system_error>
#include <utility>
#include <vector>

#include "include/pciem_api.h"

namespace socpuppet {

namespace {

[[noreturn]] void Refused(const char* what) {
  throw std::system_error(errno, std::generic_category(), what);
}

template <typename Request, typename Argument>
void Ask(int fd, Request request, Argument& argument, const char* what) {
  if (ioctl(fd, request, &argument) < 0) Refused(what);
}

// A file this program opened, closed when it goes.
class File {
 public:
  // Takes `fd`, which an open() or the like returned. A negative one is
  // the call's refusal, which throws, naming `what`.
  File(int fd, const char* what) : fd_(fd) {
    if (fd_ < 0) Refused(what);
  }
  File(File&& other) noexcept : fd_(std::exchange(other.fd_, -1)) {}
  ~File() {
    if (fd_ >= 0) close(fd_);
  }
  File(const File&) = delete;
  File& operator=(const File&) = delete;
  File& operator=(File&&) = delete;

  int Fd() const { return fd_; }

 private:
  int fd_;
};

// Memory of a file's, mapped into this program, unmapped when it goes.
class Mapping {
 public:
  // Maps `size` bytes of `file` from its start, or throws, naming `what`.
  Mapping(const File& file, std::size_t size, const char* what)
      : address_(mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED,
                      file.Fd(), 0)),
        size_(size) {
    if (address_ == MAP_FAILED) Refused(what);
  }
  ~Mapping() { munmap(address_, size_); }
  Mapping(const Mapping&) = delete;
  Mapping& operator=(const Mapping&) = delete;

  std::span<std::uint8_t> Bytes() const {
    return {static_cast<std::uint8_t*>(address_), size_};
  }
  template <typename Structure>
  Structure& As() const {
    return *static_cast<Structure*>(address_);
  }

 private:
  void* address_;
  std::size_t size_;
};

// The MSI-X table and its pending bits go in BAR2, as pciem's NVMe
// example has them. ⚠️ The table has room below the pending bits for 256
// vectors, its 16 bytes each.
constexpr std::uint32_t kMsixBar = 2;
constexpr std::uint32_t kMsixBarSize = 8192;
constexpr std::uint32_t kPendingBitsAt = 4096;

// /dev/pciem, with a device created on it: what CREATE_DEVICE and the
// calls after it until REGISTER are made on.
File CreateDevice(const PciemShape& shape, int event_fd) {
  File pciem(open("/dev/pciem", O_RDWR | O_CLOEXEC),
             "open /dev/pciem (is pciem.ko loaded?)");
  const int fd = pciem.Fd();

  pciem_create_device create{};
  create.flags = PCIEM_CREATE_FLAG_BUS_MODE_VIRTUAL;
  Ask(fd, PCIEM_IOCTL_CREATE_DEVICE, create, "CREATE_DEVICE");

  pciem_config_space config{};
  config.vendor_id = shape.identity.vendor_id;
  config.device_id = shape.identity.device_id;
  config.subsys_vendor_id = shape.identity.vendor_id;
  config.subsys_device_id = shape.identity.device_id;
  config.revision = 1;
  // pciem takes the class code lowest byte first.
  for (std::size_t i = 0; i < 3; ++i) {
    config.class_code[i] =
        static_cast<std::uint8_t>(shape.identity.class_code >> (8 * i));
  }
  Ask(fd, PCIEM_IOCTL_SET_CONFIG, config, "SET_CONFIG");

  pciem_bar_config bar0{};
  bar0.bar_index = 0;
  bar0.size = shape.function_size;
  Ask(fd, PCIEM_IOCTL_ADD_BAR, bar0, "ADD_BAR 0");
  pciem_bar_config bar2{};
  bar2.bar_index = kMsixBar;
  bar2.size = kMsixBarSize;
  Ask(fd, PCIEM_IOCTL_ADD_BAR, bar2, "ADD_BAR 2");

  pciem_cap_config msix{};
  msix.cap_type = PCIEM_CAP_MSIX;
  msix.msix.bar_index = kMsixBar;
  msix.msix.table_offset = 0;
  msix.msix.pba_offset = kPendingBitsAt;
  msix.msix.table_size = shape.vectors;
  Ask(fd, PCIEM_IOCTL_ADD_CAPABILITY, msix, "ADD_CAPABILITY MSI-X");

  // pciem posts the host's writes to BAR0, and only those.
  pciem_trace_bar trace{};
  trace.bar_index = 0;
  trace.flags = PCIEM_TRACE_WRITES;
  Ask(fd, PCIEM_IOCTL_TRACE_BAR, trace, "TRACE_BAR 0");

  pciem_eventfd_config events{};
  events.eventfd = event_fd;
  Ask(fd, PCIEM_IOCTL_SET_EVENTFD, events, "SET_EVENTFD");
  return pciem;
}

// A device on this machine's bus, through /dev/pciem. In the order they
// are made: the eventfd pciem says on that it has posted something,
// /dev/pciem with the device created on it, the device's own file that
// pciem hands back when it is registered, BAR0's memory, and the ring.
// Each is let go of, the other way round, when the device goes, or when a
// step after it is refused.
class DevPciem : public PciemDevice {
 public:
  explicit DevPciem(const PciemShape& shape)
      : events_(eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK), "eventfd"),
        pciem_(CreateDevice(shape, events_.Fd())),
        instance_(ioctl(pciem_.Fd(), PCIEM_IOCTL_REGISTER), "REGISTER"),
        bar0_(instance_, shape.function_size, "mmap BAR0"),
        ring_(pciem_, sizeof(pciem_shared_ring), "mmap the ring") {
    // 📮 pciem gives BAR0 memory as it finds it: what an earlier device
    // left there, or what was there before boot. The host reads every
    // register, the ones nobody writes too, so they start at zero
    // (docs/upstream.md, "A BAR's memory is not cleared before the host
    // reads it").
    std::ranges::fill(bar0_.Bytes(), std::uint8_t{0});
  }

  void Start() override {
    if (ioctl(pciem_.Fd(), PCIEM_IOCTL_START, 0) < 0) Refused("START");
  }

  int EventFd() const override { return events_.Fd(); }

  std::vector<HostWrite> Drain() override {
    std::uint64_t count = 0;
    // Nothing to read is fine: the count is cleared either way.
    [[maybe_unused]] const ssize_t got =
        read(events_.Fd(), &count, sizeof count);
    return DrainRing(ring_.As<pciem_shared_ring>());
  }

  std::span<std::uint8_t> Bar0() override { return bar0_.Bytes(); }

  void Dma(std::uint64_t address, std::span<std::uint8_t> data,
           bool to_host) override {
    pciem_dma_op op{};
    op.guest_iova = address;
    op.user_addr = reinterpret_cast<std::uint64_t>(data.data());
    op.length = static_cast<std::uint32_t>(data.size());
    op.flags = to_host ? PCIEM_DMA_FLAG_WRITE : PCIEM_DMA_FLAG_READ;
    Ask(pciem_.Fd(), PCIEM_IOCTL_DMA, op, "DMA");
  }

  void InjectIrq(unsigned vector) override {
    pciem_irq_inject irq{};
    irq.vector = vector;
    Ask(pciem_.Fd(), PCIEM_IOCTL_INJECT_IRQ, irq, "INJECT_IRQ");
  }

 private:
  File events_;
  File pciem_;
  File instance_;
  Mapping bar0_;
  Mapping ring_;
};

}  // namespace

std::vector<HostWrite> DrainRing(pciem_shared_ring& ring) {
  std::vector<HostWrite> writes;
  for (;;) {
    const int head = atomic_load(&ring.head);
    if (head == atomic_load(&ring.tail)) break;
    const pciem_event& event = ring.events[head];
    if (event.type == PCIEM_EVENT_MMIO_WRITE) {
      writes.push_back({.bar = event.bar,
                        .offset = event.offset,
                        .size = event.size,
                        .data = event.data});
    }
    atomic_store(&ring.head, (head + 1) % PCIEM_RING_SIZE);
  }
  return writes;
}

std::unique_ptr<PciemDevice> OpenPciemDevice(const PciemShape& shape) {
  return std::make_unique<DevPciem>(shape);
}

}  // namespace socpuppet
