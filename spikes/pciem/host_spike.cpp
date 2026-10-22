// spike_pciem_host: puts one of the puppet's NVMe drives on this machine's
// own PCIe bus, through pciem, and runs it until Ctrl-C.
//
//   spike_pciem_host <behavioral|stand-in|zephyr> [--blocks N] [--vectors N]
//                    [--board FILE] [--elf FILE] [--log]
//
// See README.md here for what it needs first (pciem.ko loaded, which needs
// root and a reservation at boot).
#include <poll.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <format>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/ns16550.h"
#include "socpuppet/platform/logging.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "spikes/pciem/pciem_bridge.h"
#include "spikes/pciem/pciem_device.h"
#include "spikes/pciem/rigs.h"

namespace {

using Clock = std::chrono::steady_clock;
using sc_core::sc_time;

volatile std::sig_atomic_t stopping = 0;
void Stop(int) { stopping = 1; }

// PciemDevice as the bridge sees it.
class DeviceHost : public spike::HostSide {
 public:
  explicit DeviceHost(spike::PciemDevice* device) : device_(device) {}
  void Dma(std::uint64_t address, std::span<std::uint8_t> data,
           bool to_host) override {
    device_->Dma(address, data, to_host);
  }
  void InjectIrq(unsigned vector) override { device_->InjectIrq(vector); }

 private:
  spike::PciemDevice* device_;
};

// The registers the host reads and only the device changes: CAP, VS and
// CSTS. The rest it reads back as it wrote them, which pciem's shadow
// write already did.
std::string Tally(const spike::BridgeCounts& c) {
  return std::format(
      "writes {} (refused {}), dma {} ({} KiB, failed {}), irqs {} (+{} "
      "again)",
      c.writes, c.refused_writes, c.dma_transfers, c.dma_bytes / 1024,
      c.dma_failures, c.interrupts, c.reinjected);
}

struct Register {
  std::uint64_t offset;
  std::size_t size;
};
constexpr std::array<Register, 3> kReadOnly{{{.offset = 0x00, .size = 8},
                                             {.offset = 0x08, .size = 4},
                                             {.offset = 0x1C, .size = 4}}};
constexpr std::uint64_t kCc = 0x14;
constexpr std::uint64_t kCsts = 0x1C;

double Seconds(Clock::duration duration) {
  return std::chrono::duration<double>(duration).count();
}

// Copies the read-only registers from the function into BAR0's memory.
// Returns CSTS.
// CAP.TO, the longest the host should wait for CSTS.RDY, in 500 ms
// units, is CAP's fourth byte. Linux waits (TO + 1) / 2 whole seconds, so
// a TO of 0 is no wait at all: it reads CSTS once after setting CC.EN,
// sleeps a millisecond or two, and gives up. A device played from user
// space cannot be ready that fast, so `least_timeout` raises it.
constexpr std::size_t kTimeoutByte = 3;

std::uint32_t Refresh(socpuppet::Platform& platform,
                      std::span<std::uint8_t> bar0,
                      std::uint8_t least_timeout) {
  std::uint32_t csts = 0;
  for (const Register& r : kReadOnly) {
    std::array<std::byte, 8> value{};
    if (!platform.DebugRead("pciem.bar0", r.offset, {value.data(), r.size})) {
      continue;
    }
    if (r.offset == 0) {
      auto& timeout = reinterpret_cast<std::uint8_t&>(value[kTimeoutByte]);
      timeout = std::max(timeout, least_timeout);
    }
    std::memcpy(bar0.data() + r.offset, value.data(), r.size);
    if (r.offset == kCsts) std::memcpy(&csts, value.data(), sizeof csts);
  }
  std::atomic_thread_fence(std::memory_order_release);
  return csts;
}

std::optional<spike::Options> Parse(int argc, char** argv) {
  if (argc < 2) return std::nullopt;
  spike::Options options;
  options.drive = argv[1];
  if (options.drive != "behavioral" && options.drive != "stand-in" &&
      options.drive != "zephyr") {
    return std::nullopt;
  }
  for (int i = 2; i < argc; ++i) {
    const std::string_view arg = argv[i];
    const bool has_value = i + 1 < argc;
    if (arg == "--log") {
      options.log = true;
    } else if (arg == "--least-timeout" && has_value) {
      options.least_timeout = static_cast<std::uint8_t>(std::stoul(argv[++i]));
    } else if (arg == "--dry-run") {
      options.dry_run = true;
    } else if (arg == "--blocks" && has_value) {
      options.blocks = std::stoull(argv[++i]);
    } else if (arg == "--vectors" && has_value) {
      options.vectors = static_cast<unsigned>(std::stoul(argv[++i]));
    } else if (arg == "--board" && has_value) {
      options.board = argv[++i];
    } else if (arg == "--elf" && has_value) {
      options.elf = argv[++i];
    } else {
      return std::nullopt;
    }
  }
  return options;
}

// How far ahead the next activity may be for the drive to count as busy,
// and how much simulated time to run it for before looking at the host
// again: a quantum, for a drive with a CPU.
const sc_time kSlice(100, sc_core::SC_US);

}  // namespace

// NOLINTNEXTLINE(bugprone-exception-escape)
int main(int argc, char** argv) {
  const std::optional<spike::Options> options = Parse(argc, argv);
  if (!options) {
    std::fprintf(stderr,
                 "usage: %s <behavioral|stand-in|zephyr> [--blocks N] "
                 "[--vectors N] [--board FILE] [--elf FILE] [--log] "
                 "[--least-timeout N] [--dry-run]\n",
                 argv[0]);
    return 2;
  }
  socpuppet::InitLogging(false);

  std::optional<spike::PciemDevice> device;
  if (!options->dry_run) {
    device.emplace(spike::PciemDevice::Shape{
        .vendor = 0x1b36,  // QEMU's NVMe, as a placeholder
        .device = 0x0010,
        .bar0_size = 0x2000,
        .vectors = static_cast<std::uint16_t>(options->vectors)});
  }
  DeviceHost host(device ? &*device : nullptr);

  socpuppet::Registry registry = socpuppet::BuiltinComponents();
  spike::AddPciemBridge(registry, "pciem_bridge", host);
  if (options->drive == "stand-in") spike::RegisterStandIn(registry);
  socpuppet::Platform platform(std::move(registry));
  const spike::Wiring wiring =
      options->drive == "behavioral" ? spike::AddBehavioral(platform, *options)
      : options->drive == "stand-in" ? spike::AddStandIn(platform, *options)
                                     : spike::AddZephyr(platform, *options);
  platform.Add("pciem", "pciem_bridge", {{"vectors", options->vectors}});
  platform.Bind("pciem.bar0", wiring.registers);
  platform.Bind(wiring.dma, "pciem.dma");
  for (unsigned v = 0; v < options->vectors; ++v) {
    platform.Bind(wiring.irq_prefix + std::to_string(v),
                  "pciem.irq" + std::to_string(v));
  }
  if (wiring.quantum != sc_time()) platform.SetQuantum(wiring.quantum);
  platform.Elaborate();
  if (options->drive == "zephyr") spike::LoadFirmware(platform, *options);
  auto& bridge = platform.ModuleAt<spike::PciemBridge>("pciem");
  bridge.LogRegisterWrites(options->log);

  // A drive with firmware boots first, so that it is ready before the
  // host's driver asks.
  const Clock::time_point booting = Clock::now();
  if (wiring.boot != sc_time()) platform.Run(wiring.boot);
  std::printf("[%9.3f] %s: booted in %s simulated\n",
              Seconds(Clock::now() - booting), options->drive.c_str(),
              platform.Time().to_string().c_str());

  if (options->drive == "zephyr") {
    std::printf("%s",
                platform.ModuleAt<socpuppet::Ns16550>("uart").Output().c_str());
  }
  if (options->dry_run) return 0;
  std::uint32_t csts =
      Refresh(platform, device->Bar0(), options->least_timeout);
  std::signal(SIGINT, Stop);
  std::signal(SIGTERM, Stop);
  device->Start();
  const Clock::time_point start = Clock::now();
  std::printf("[%9.3f] on the bus; Ctrl-C takes it off\n", 0.0);
  std::fflush(stdout);

  std::optional<Clock::time_point> enabled_at;
  Clock::duration asleep{};
  Clock::duration running{};
  std::uint64_t wakes = 0;
  std::size_t deepest_drain = 0;
  Clock::time_point last_report = start;
  std::vector<spike::HostWrite> writes;
  pollfd events{.fd = device->EventFd(), .events = POLLIN, .revents = 0};

  try {
    while (stopping == 0) {
      writes.clear();
      device->Drain(writes);
      deepest_drain = std::max(deepest_drain, writes.size());
      for (const spike::HostWrite& w : writes) {
        if (w.bar == 0 && w.offset == kCc && (w.data & 1) != 0 && !enabled_at &&
            (csts & 1) == 0) {
          enabled_at = Clock::now();
          std::printf("[%9.3f] CC.EN set\n", Seconds(*enabled_at - start));
        }
      }
      bridge.Take(writes);

      const Clock::time_point before = Clock::now();
      const std::optional<sc_time> ahead = platform.TimeToNextActivity();
      const bool awake = ahead && *ahead <= kSlice;
      if (awake) platform.Run(kSlice);
      running += Clock::now() - before;

      const std::uint32_t was = csts;
      csts = Refresh(platform, device->Bar0(), options->least_timeout);
      if ((was & 1) != (csts & 1)) {
        const Clock::time_point now = Clock::now();
        std::printf("[%9.3f] CSTS.RDY %u", Seconds(now - start), csts & 1);
        if (enabled_at && (csts & 1) != 0) {
          std::printf(", %.3f ms after CC.EN",
                      1e3 * Seconds(now - *enabled_at));
        }
        std::printf("\n");
        if ((csts & 1) == 0) enabled_at.reset();
      }

      const Clock::time_point now = Clock::now();
      if (now - last_report > std::chrono::seconds(5)) {
        last_report = now;
        std::printf("[%9.3f] simulated %s; %s\n", Seconds(now - start),
                    platform.Time().to_string().c_str(),
                    Tally(bridge.Counts()).c_str());
      }
      std::fflush(stdout);
      if (awake || bridge.Busy()) continue;

      // 💤 Nothing is due soon: wait for the host, or for the next thing
      // the drive has scheduled, and let simulated time follow wall time.
      const sc_time limit = ahead
                                ? std::min(*ahead, sc_time(1, sc_core::SC_SEC))
                                : sc_time(1, sc_core::SC_SEC);
      const auto timeout_ms =
          static_cast<int>(std::max(1.0, limit.to_seconds() * 1e3));
      const Clock::time_point slept = Clock::now();
      ++wakes;
      poll(&events, 1, timeout_ms);
      const Clock::duration waited = Clock::now() - slept;
      asleep += waited;
      platform.Run(sc_time(Seconds(waited), sc_core::SC_SEC));
    }
  } catch (const std::exception& failure) {
    std::printf("the simulation stopped: %s\n", failure.what());
  }

  std::printf("\n%s", std::format("{}, {:.3f} s on the bus: {:.3f} s asleep, "
                                  "{:.3f} s simulating, {} waits, deepest "
                                  "drain {}\n{}, simulated {}\n",
                                  options->drive, Seconds(Clock::now() - start),
                                  Seconds(asleep), Seconds(running), wakes,
                                  deepest_drain, Tally(bridge.Counts()),
                                  platform.Time().to_string())
                          .c_str());
  return 0;
}
