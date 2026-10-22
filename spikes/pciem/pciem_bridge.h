#ifndef SPIKES_PCIEM_PCIEM_BRIDGE_H_
#define SPIKES_PCIEM_PCIEM_BRIDGE_H_

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <exception>
#include <format>
#include <memory>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/pciem/pciem_device.h"

namespace spike {

// What the bridge needs of the real host: its memory and its interrupts.
// PciemDevice in a run; a fake in the spike's tests.
class HostSide {
 public:
  virtual ~HostSide() = default;
  virtual void Dma(std::uint64_t address, std::span<std::uint8_t> data,
                   bool to_host) = 0;
  virtual void InjectIrq(unsigned vector) = 0;
};

// What the bridge counted, for the pump's reports.
struct BridgeCounts {
  std::uint64_t writes = 0;
  std::uint64_t refused_writes = 0;
  std::uint64_t dma_transfers = 0;
  std::uint64_t dma_bytes = 0;
  std::uint64_t dma_failures = 0;
  std::uint64_t interrupts = 0;
  std::uint64_t reinjected = 0;
};

// The NVMe function's other side: where a PcieEndpoint would sit in the
// puppet, this sits and hands everything to the machine's own host.
//
//   this machine's Linux ══ pciem ══ bridge ─ bar0 ─▶ the function's registers
//                                      ▲ ◀─ dma ───── the function's DMA
//                                      └─── irq ◀──── its interrupt lines
//
// `bar0` carries the host's register writes in, `dma` the function's
// accesses to the host's memory out, and a line of `irq` going high sends
// that vector. The host's reads do not come through here at all (see
// pciem_device.h): the pump copies the registers the host reads into
// BAR0's memory.
class PciemBridge : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<PciemBridge> bar0{"bar0"};
  tlm_utils::simple_target_socket<PciemBridge> dma{"dma"};
  sc_core::sc_vector<sc_core::sc_in<bool>> irq;

  PciemBridge(const sc_core::sc_module_name& name, std::size_t vectors,
              HostSide& host)
      : sc_module(name), irq("irq", vectors), host_(host) {
    dma.register_b_transport(this, &PciemBridge::DmaTransport);
    SC_THREAD(Deliver);
    SC_METHOD(Interrupt);
    for (sc_core::sc_in<bool>& line : irq) sensitive << line.pos();
    dont_initialize();
  }

  // Hands the host's writes over, to be made on `bar0` in order once the
  // simulation runs. Called from outside it, between runs.
  void Take(std::span<const HostWrite> writes) {
    if (writes.empty()) return;
    pending_.insert(pending_.end(), writes.begin(), writes.end());
    arrived_.notify(sc_core::SC_ZERO_TIME);
  }

  bool Busy() const { return !pending_.empty(); }
  const BridgeCounts& Counts() const { return counts_; }
  // Prints each controller register write (not the doorbells) and each
  // refusal, as it is made.
  void LogRegisterWrites(bool log) { log_ = log; }

 private:
  // Where the doorbells start, and the stride between them: DSTRD is 0.
  static constexpr std::uint64_t kDoorbells = 0x1000;
  static constexpr std::uint64_t kDoorbellStride = 4;

  void Deliver() {
    for (;;) {
      wait(arrived_);
      bool acknowledged = false;
      while (!pending_.empty()) {
        const HostWrite write = pending_.front();
        pending_.pop_front();
        if (write.bar != 0) continue;
        acknowledged |= IsCompletionHeadDoorbell(write.offset);
        Make(write);
      }
      // The lines are levels and MSI-X is edges. A completion posted while
      // the host was still working through the last ones keeps the line
      // high, so there is no new edge: send the vector again once the host
      // has said how far it got, as a device with pending bits would.
      if (acknowledged) {
        // The drive lowers its line in answer to the doorbell, and a
        // signal changes a delta cycle after it is written.
        wait(sc_core::SC_ZERO_TIME);
        for (std::size_t vector = 0; vector < irq.size(); ++vector) {
          if (!irq[vector].read()) continue;
          host_.InjectIrq(static_cast<unsigned>(vector));
          ++counts_.reinjected;
        }
      }
    }
  }

  static bool IsCompletionHeadDoorbell(std::uint64_t offset) {
    return offset >= kDoorbells &&
           ((offset - kDoorbells) / kDoorbellStride) % 2 == 1;
  }

  void Make(const HostWrite& write) {
    std::vector<std::uint8_t> bytes(write.size);
    for (std::size_t i = 0; i < bytes.size(); ++i) {
      bytes[i] = static_cast<std::uint8_t>(write.data >> (8 * i));
    }
    tlm::tlm_generic_payload transaction;
    transaction.set_command(tlm::TLM_WRITE_COMMAND);
    transaction.set_address(write.offset);
    transaction.set_data_ptr(bytes.data());
    transaction.set_data_length(write.size);
    transaction.set_streaming_width(write.size);
    transaction.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    bar0->b_transport(transaction, delay);
    ++counts_.writes;
    const bool ok = transaction.is_response_ok();
    if (!ok) ++counts_.refused_writes;
    if (log_ && (write.offset < kDoorbells || !ok)) {
      std::fputs(
          std::format("write 0x{:04x} size {} data 0x{:x}{}\n", write.offset,
                      write.size, write.data, ok ? "" : "  REFUSED")
              .c_str(),
          stdout);
    }
  }

  void DmaTransport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const bool to_host = transaction.is_write();
    try {
      host_.Dma(transaction.get_address(),
                {transaction.get_data_ptr(), transaction.get_data_length()},
                to_host);
      ++counts_.dma_transfers;
      counts_.dma_bytes += transaction.get_data_length();
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    } catch (const std::exception& refused) {
      ++counts_.dma_failures;
      std::fputs(std::format("dma {} 0x{:x} length {} FAILED: {}\n",
                             to_host ? "to host" : "from host",
                             transaction.get_address(),
                             transaction.get_data_length(), refused.what())
                     .c_str(),
                 stdout);
      transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
    }
  }

  void Interrupt() {
    for (std::size_t vector = 0; vector < irq.size(); ++vector) {
      if (!irq[vector].posedge()) continue;
      host_.InjectIrq(static_cast<unsigned>(vector));
      ++counts_.interrupts;
    }
  }

  HostSide& host_;
  std::deque<HostWrite> pending_;
  sc_core::sc_event arrived_;
  BridgeCounts counts_;
  bool log_ = false;
};

// Adds the bridge to a registry as `implementation`, talking to `host`.
// It takes one parameter, `vectors`.
inline void AddPciemBridge(socpuppet::Registry& registry,
                           std::string implementation, HostSide& host) {
  registry.Add(std::move(implementation),
               [&host](const char* name, socpuppet::Parameters& parameters) {
                 auto module = std::make_unique<PciemBridge>(
                     name, parameters.Required("vectors", {1, 2048}), host);
                 std::vector<socpuppet::Port> ports{
                     socpuppet::InitiatorPort("bar0", module->bar0),
                     socpuppet::TargetPort("dma", module->dma)};
                 for (std::size_t v = 0; v < module->irq.size(); ++v) {
                   ports.push_back(socpuppet::WireSinkPort(
                       "irq" + std::to_string(v), module->irq[v]));
                 }
                 return socpuppet::Instance{.module = std::move(module),
                                            .ports = std::move(ports)};
               });
}

}  // namespace spike

#endif  // SPIKES_PCIEM_PCIEM_BRIDGE_H_
