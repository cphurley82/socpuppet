#ifndef SOCPUPPET_MODELS_BEHAVIORAL_NVME_H_
#define SOCPUPPET_MODELS_BEHAVIORAL_NVME_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/nvme_controller.h"
#include "socpuppet/models/interrupt_lines.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

// Stand-in for an NVMe SSD: a controller that answers the host itself, with
// no CPU or firmware behind it. This is the SystemC wrapper, and the logic
// is in NvmeController.
//
// It is an NVMe function with no PCIe around it: `bar0` is the register
// block a PCIe endpoint would put behind its first base address register,
// and `dma` is how the controller reads and writes the host's memory.
//
// A write to a doorbell returns at once, and the command is carried out by
// a process of the controller's own, one delta cycle later at the same
// simulated time. (A delta cycle is one round of the simulator letting every
// process that is ready run, with no time passing.) A real controller works
// in parallel with the host in the same way. There is an engineering reason
// too: carrying a command out means DMA, and DMA started from inside the
// doorbell write would go back onto the bus that the host's own access is
// still crossing.
//
// An interrupt line is high while the controller has a completion the host
// has not acknowledged. An acknowledgement makes it fall, and if
// completions are still waiting it rises again one delta cycle after. The
// host is told about an interrupt when the line rises (that is when a PCIe
// endpoint sends an MSI-X message), so a line that stayed high for the
// completions still waiting would tell it nothing.
class BehavioralNvme : public sc_core::sc_module,
                       private NvmeController::HostMemory {
 public:
  tlm_utils::simple_target_socket<BehavioralNvme> bar0{"bar0"};
  tlm_utils::simple_initiator_socket<BehavioralNvme> dma{"dma"};
  // One interrupt line per vector.
  sc_core::sc_vector<sc_core::sc_out<bool>> irq;

  // `blocks` is how many 512-byte blocks the drive holds, and `vectors`
  // how many interrupt lines it has.
  BehavioralNvme(const sc_core::sc_module_name& name, std::uint64_t blocks,
                 std::size_t vectors)
      : sc_module(name),
        irq("irq", vectors),
        controller_(*this, blocks, vectors),
        interrupt_lines_("interrupt_lines", irq, controller_) {
    bar0.register_b_transport(this, &BehavioralNvme::b_transport);
    bar0.register_transport_dbg(this, &BehavioralNvme::transport_dbg);
    SC_THREAD(Work);
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    const bool ok =
        transaction.is_read()
            ? controller_.ReadRegister(transaction.get_address(), data)
            : controller_.WriteRegister(transaction.get_address(), data);
    transaction.set_response_status(ok ? tlm::TLM_OK_RESPONSE
                                       : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    if (transaction.is_write()) {
      // The lines first, so that a fall is visible before the controller
      // can have done anything about the write.
      interrupt_lines_.Update();
      work_.notify(sc_core::SC_ZERO_TIME);
    }
  }

  // Debug transport: the register block as a debugger sees it, in no
  // simulated time. A write lands in the register and sets no work going:
  // a doorbell rung this way is answered at the host's next real write.
  // Returns the bytes transferred, which is none if nothing is there.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    const bool ok =
        transaction.is_read()
            ? controller_.ReadRegister(transaction.get_address(), data)
            : controller_.WriteRegister(transaction.get_address(), data);
    return ok ? transaction.get_data_length() : 0;
  }

  void Work() {
    for (;;) {
      wait(work_);
      // A loop, because the host may have rung the doorbell more than once
      // before this process got its turn.
      while (controller_.CarryOutOne()) interrupt_lines_.Update();
    }
  }

  // NvmeController::HostMemory: the controller's DMA.
  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return Transport(dma, tlm::TLM_READ_COMMAND, address, out) ==
           tlm::TLM_OK_RESPONSE;
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return Transport(dma, tlm::TLM_WRITE_COMMAND, address, WriteData(in)) ==
           tlm::TLM_OK_RESPONSE;
  }

  NvmeController controller_;
  // Writes `irq` from what the controller asks for.
  InterruptLines interrupt_lines_;
  // Notified when the host has written to a register, which may have given
  // the controller something to do.
  sc_core::sc_event work_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_BEHAVIORAL_NVME_H_
