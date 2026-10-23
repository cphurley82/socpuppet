#ifndef SOCPUPPET_MODELS_PCIEM_HOST_H_
#define SOCPUPPET_MODELS_PCIEM_HOST_H_

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/pciem_device.h"
#include "socpuppet/core/pciem_host_logic.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

// What a PciemHost has counted.
struct PciemCounts {
  // The host's writes that the function refused.
  std::uint64_t refused_writes = 0;
};

// 🐧 This machine's own Linux as the host of a PCIe function, through
// pciem (pciem_device.h). It stands where a PCIe endpoint, its link and
// the puppet's root complex would, and hands everything to the real host:
//
//   this machine's Linux ══ pciem ══ PciemHost ── bar0 ──▶ the function
//                                              ◀── dma ─── its DMA     🚧
//                                              ◀── irq ─── its lines   🚧
//
// `bar0` carries the host's register writes in. The host's reads do not
// come through here at all: they read pciem's copy of BAR0.
class PciemHost : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<PciemHost> bar0{"bar0"};
  tlm_utils::simple_target_socket<PciemHost> dma{"dma"};
  sc_core::sc_vector<sc_core::sc_in<bool>> irq;

  PciemHost(const sc_core::sc_module_name& name, std::size_t vectors,
            std::unique_ptr<PciemDevice> device)
      : sc_module(name), irq("irq", vectors), device_(std::move(device)) {
    SC_THREAD(Deliver);
  }

  // Hands the host's writes over, to be made on `bar0` in order once the
  // simulation runs. Called from outside it, between runs.
  void Take(std::span<const HostWrite> writes) {
    pending_.insert(pending_.end(), writes.begin(), writes.end());
    arrived_.notify(sc_core::SC_ZERO_TIME);
  }

  const PciemCounts& Counts() const { return counts_; }

 private:
  // 💡 The writes arrive from outside the simulation, and are made from
  // inside it, a delta cycle later, by a thread of the host's own: a
  // transaction needs a process to be made from.
  void Deliver() {
    for (;;) {
      wait(arrived_);
      while (!pending_.empty()) {
        Make(pending_.front());
        pending_.pop_front();
      }
    }
  }

  // pciem is asked to post the writes to BAR0 alone, so each is one to
  // the function's registers.
  void Make(const HostWrite& write) {
    std::vector<std::uint8_t> bytes = BytesOf(write);
    if (Transport(bar0, tlm::TLM_WRITE_COMMAND, write.offset, bytes) !=
        tlm::TLM_OK_RESPONSE) {
      ++counts_.refused_writes;
    }
  }

  std::unique_ptr<PciemDevice> device_;
  std::deque<HostWrite> pending_;
  sc_core::sc_event arrived_;
  PciemCounts counts_;
};

// Opens the device a PciemHost is given, in the shape its parameters say.
using PciemDeviceOpener =
    std::function<std::unique_ptr<PciemDevice>(const PciemShape&)>;

// Adds PciemHost to a registry as `implementation`, with a device from
// `open`. Its parameters are those of a "pcie_endpoint": `vendor_id`,
// `device_id`, `class_code`, `function_size` and `vectors`.
inline void AddPciemHost(Registry& registry, std::string implementation,
                         PciemDeviceOpener open) {
  registry.Add(
      std::move(implementation),
      [open = std::move(open)](const char* name, Parameters& parameters) {
        const PciemShape shape{
            .identity = {.vendor_id = static_cast<std::uint16_t>(
                             parameters.Required("vendor_id", kFitsIn16Bits)),
                         .device_id = static_cast<std::uint16_t>(
                             parameters.Required("device_id", kFitsIn16Bits)),
                         .class_code = static_cast<std::uint32_t>(
                             parameters.Required("class_code", kFitsIn24Bits))},
            .function_size = parameters.Required("function_size"),
            .vectors = static_cast<std::uint16_t>(
                parameters.Required("vectors", kInterruptVectors))};
        auto module =
            std::make_unique<PciemHost>(name, shape.vectors, open(shape));
        std::vector<Port> ports{InitiatorPort("bar0", module->bar0),
                                TargetPort("dma", module->dma)};
        AddNumberedPorts(ports, "irq", 0, module->irq, WireSinkPort);
        return Instance{.module = std::move(module), .ports = std::move(ports)};
      });
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PCIEM_HOST_H_
