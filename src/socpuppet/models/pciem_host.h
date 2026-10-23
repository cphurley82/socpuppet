#ifndef SOCPUPPET_MODELS_PCIEM_HOST_H_
#define SOCPUPPET_MODELS_PCIEM_HOST_H_

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/nvme_host_registers.h"
#include "socpuppet/core/pciem_device.h"
#include "socpuppet/core/pciem_host_logic.h"
#include "socpuppet/models/tie_low.h"
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
//                                              ◀── dma ─── its DMA
//                                              ◀── irq ─── its lines
//
// 🎓 It knows two things of NVMe, the function behind it: which of the
// host's writes acknowledge completions (SendHighLinesAgain), and which
// registers the function says for itself (Refresh).
//
// `bar0` carries the host's register writes in, `dma` the function's
// accesses to the host's memory out, and a line of `irq` that rises sends
// the host that vector. The host's reads do not come through here at all:
// they read pciem's copy of BAR0.
class PciemHost : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<PciemHost> bar0{"bar0"};
  tlm_utils::simple_target_socket<PciemHost> dma{"dma"};
  sc_core::sc_vector<sc_core::sc_in<bool>> irq;

  PciemHost(const sc_core::sc_module_name& name, std::size_t vectors,
            std::unique_ptr<PciemDevice> device)
      : sc_module(name), irq("irq", vectors), device_(std::move(device)) {
    dma.register_b_transport(this, &PciemHost::DmaTransport);
    SC_THREAD(Deliver);
    SC_METHOD(SendRisingLines);
    for (sc_core::sc_in<bool>& line : irq) sensitive << line.pos();
    dont_initialize();
  }

  // An interrupt line that nothing is connected to is tied low.
  void before_end_of_elaboration() override {
    TieLowIfUnconnected(irq, tied_low_);
  }

  // Takes the writes pciem has posted, to be made on `bar0` in order once
  // the simulation runs. Called from outside it, between runs, whenever
  // pciem may have posted writes; with none posted it does nothing.
  void Service() {
    const std::vector<HostWrite> posted = device_->Drain();
    pending_.insert(pending_.end(), posted.begin(), posted.end());
    arrived_.notify(sc_core::SC_ZERO_TIME);
  }

  // Refreshes pciem's copy of BAR0, which the host reads, with the
  // registers the function says (CAP, VS and CSTS) as they are now. The
  // rest the host reads back as it wrote them, from pciem's copy of its
  // writes. Called from outside the simulation, between runs: the reads
  // are debug accesses, which take no time.
  void Refresh() {
    const std::span<std::uint8_t> copy = device_->Bar0();
    for (const NvmeHostRegisters::Register& says :
         NvmeHostRegisters::RegistersTheControllerSays()) {
      DebugTransport(bar0, tlm::TLM_READ_COMMAND, says.offset,
                     copy.subspan(says.offset, says.size));
    }
  }

  const PciemCounts& Counts() const { return counts_; }

 private:
  // 💡 The writes arrive from outside the simulation, and are made from
  // inside it, a delta cycle later, by a thread of the host's own: a
  // transaction needs a process to be made from.
  void Deliver() {
    for (;;) {
      wait(arrived_);
      bool acknowledged = false;
      while (!pending_.empty()) {
        acknowledged |= NvmeHostRegisters::IsCompletionHeadDoorbell(
            pending_.front().offset);
        Make(pending_.front());
        pending_.pop_front();
      }
      if (acknowledged) SendHighLinesAgain();
    }
  }

  // 🎓 The function's lines are levels, and the host is sent a vector only
  // when one rises. A completion queue's head doorbell lowers its line and
  // raises it again if completions are still waiting, but only if no other
  // queue on the same vector holds the line high through it. Under pciem
  // that is the usual case: the host has one interrupt, so the admin queue
  // and the I/O queue share vector 0. NVMe asks a controller to send a new
  // message once a head doorbell leaves entries in a queue, so once the
  // host has said how far it got, a vector whose line is still high is
  // sent again.
  void SendHighLinesAgain() {
    // The function writes its line in the delta of the doorbell's write,
    // as InterruptLines does, and a signal changes a delta cycle after it
    // is written.
    wait(sc_core::SC_ZERO_TIME);
    for (std::size_t vector = 0; vector < irq.size(); ++vector) {
      if (irq[vector].read()) device_->InjectIrq(static_cast<unsigned>(vector));
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

  // The function's DMA, to or from the host's memory.
  void DmaTransport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    try {
      device_->Dma(transaction.get_address(),
                   {transaction.get_data_ptr(), transaction.get_data_length()},
                   transaction.is_write());
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    } catch (const std::system_error&) {
      transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
    }
  }

  // A line that rises sends its vector.
  void SendRisingLines() {
    for (std::size_t vector = 0; vector < irq.size(); ++vector) {
      if (irq[vector].posedge()) {
        device_->InjectIrq(static_cast<unsigned>(vector));
      }
    }
  }

  std::unique_ptr<PciemDevice> device_;
  std::deque<HostWrite> pending_;
  sc_core::sc_event arrived_;
  PciemCounts counts_;
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
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
