#ifndef SOCPUPPET_MODELS_NVME_FRONTEND_H_
#define SOCPUPPET_MODELS_NVME_FRONTEND_H_

#include <cstddef>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/nvme_frontend_logic.h"
#include "socpuppet/models/interrupt_lines.h"
#include "socpuppet/models/socket_memory.h"

namespace socpuppet {

// The NVMe frontend of an SSD's controller: the hardware between the host
// and the SSD's firmware. It keeps the queues, and the firmware makes the
// decisions. This is the SystemC wrapper, and the logic is in
// NvmeFrontendLogic.
//
// To the host it is an NVMe function with no PCIe around it, as the
// stand-in drive is: `bar0` is the register block a PCIe endpoint would put
// behind its first base address register, `dma` is how it reads and writes
// the host's memory, and `irq` has an interrupt line for each vector.
//
// To the SSD's own CPU it is a device on its bus: `cpu` is a second
// register block, in which the CPU finds each command the frontend has
// fetched and says what its completion is, and `cpu_irq` is high while the
// frontend has something to tell the CPU that the CPU asked to be told.
//
// A write to a register returns at once, and what it asks for in the
// host's memory (a command fetched, a completion posted) is done by a
// process of the frontend's own, one delta cycle later at the same
// simulated time. (A delta cycle is one round of the simulator letting
// every process that is ready run, with no time passing.) Real hardware
// works alongside the host and the CPU in the same way, and DMA started
// from inside the host's doorbell write would go back onto the bus that
// the host's own access is still crossing.
class NvmeFrontend : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<NvmeFrontend> bar0{"bar0"};
  tlm_utils::simple_initiator_socket<NvmeFrontend> dma{"dma"};
  // One interrupt line to the host per vector.
  sc_core::sc_vector<sc_core::sc_out<bool>> irq;
  tlm_utils::simple_target_socket<NvmeFrontend> cpu{"cpu"};
  sc_core::sc_out<bool> cpu_irq{"cpu_irq"};

  // `vectors` is how many interrupt lines it has for the host.
  NvmeFrontend(const sc_core::sc_module_name& name, std::size_t vectors)
      : sc_module(name),
        irq("irq", vectors),
        logic_(host_memory_, vectors),
        host_lines_("host_lines", irq, logic_.HostInterrupts()) {
    bar0.register_b_transport(this, &NvmeFrontend::HostTransport);
    bar0.register_transport_dbg(this, &NvmeFrontend::HostDebugTransport);
    cpu.register_b_transport(this, &NvmeFrontend::CpuTransport);
    SC_THREAD(Work);
    SC_METHOD(DriveTheCpusLine);
    sensitive << cpus_line_may_have_changed_;
    dont_initialize();
  }

 private:
  static std::span<std::uint8_t> DataOf(tlm::tlm_generic_payload& transaction) {
    return {transaction.get_data_ptr(), transaction.get_data_length()};
  }

  void HostTransport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const bool ok = transaction.is_read()
                        ? logic_.ReadHostRegister(transaction.get_address(),
                                                  DataOf(transaction))
                        : logic_.WriteHostRegister(transaction.get_address(),
                                                   DataOf(transaction));
    transaction.set_response_status(ok ? tlm::TLM_OK_RESPONSE
                                       : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    if (transaction.is_write()) SomethingMayHaveChanged();
  }

  // Debug transport: the host's register block as a debugger sees it, in
  // no simulated time. A write lands in the register and sets no work
  // going: a doorbell rung this way is answered at the next real write.
  // Returns the bytes transferred, which is none if nothing is there.
  unsigned HostDebugTransport(tlm::tlm_generic_payload& transaction) {
    const bool ok = transaction.is_read()
                        ? logic_.ReadHostRegister(transaction.get_address(),
                                                  DataOf(transaction))
                        : logic_.WriteHostRegister(transaction.get_address(),
                                                   DataOf(transaction));
    return ok ? transaction.get_data_length() : 0;
  }

  void CpuTransport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const bool ok = transaction.is_read()
                        ? logic_.ReadCpuRegister(transaction.get_address(),
                                                 DataOf(transaction))
                        : logic_.WriteCpuRegister(transaction.get_address(),
                                                  DataOf(transaction));
    transaction.set_response_status(ok ? tlm::TLM_OK_RESPONSE
                                       : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    if (transaction.is_write()) SomethingMayHaveChanged();
  }

  // After a write to either register block: the lines first, so that a
  // fall is visible before the frontend can have done anything about the
  // write, and then the work, a delta cycle on.
  void SomethingMayHaveChanged() {
    host_lines_.Update();
    cpus_line_may_have_changed_.notify();
    work_.notify(sc_core::SC_ZERO_TIME);
  }

  void Work() {
    for (;;) {
      wait(work_);
      // A loop, because there may be more than one thing to do: several
      // writes can come before this process gets its turn.
      while (logic_.Step()) {
        host_lines_.Update();
        cpus_line_may_have_changed_.notify();
      }
    }
  }

  // The only process that writes the CPU's line. A SystemC signal takes
  // one writer, and the host's accesses, the CPU's and the frontend's own
  // work all change what the line should say.
  void DriveTheCpusLine() { cpu_irq.write(logic_.CpuInterrupting()); }

  // The host's memory, as the logic reaches it for its DMA.
  SocketMemory<tlm_utils::simple_initiator_socket<NvmeFrontend>> host_memory_{
      dma};
  NvmeFrontendLogic logic_;
  // Writes `irq` from what the logic asks of the host.
  InterruptLines host_lines_;
  // Notified when a register has been written, which may have given the
  // frontend something to do in the host's memory.
  sc_core::sc_event work_;
  // Notified when what the CPU's interrupt line should say may have
  // changed.
  sc_core::sc_event cpus_line_may_have_changed_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_NVME_FRONTEND_H_
