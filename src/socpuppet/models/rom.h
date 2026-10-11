#ifndef SOCPUPPET_MODELS_ROM_H_
#define SOCPUPPET_MODELS_ROM_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/memory_store.h"

namespace socpuppet {

// A read-only memory on the bus: what a CPU's reset vector points into.
//
// A real ROM's bytes are put there when the chip is made. This one is
// loaded the way a platform loads any memory, by a debugger's write, and
// takes one until its bus master first comes to it, with a transaction or
// a request for direct memory access. From then on the chip is made, and a
// debugger can look and not touch, as on a board.
class Rom : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Rom> socket{"socket"};

  Rom(const sc_core::sc_module_name& name, std::size_t size)
      : sc_module(name), store_(size) {
    socket.register_b_transport(this, &Rom::b_transport);
    socket.register_get_direct_mem_ptr(this, &Rom::get_direct_mem_ptr);
    socket.register_transport_dbg(this, &Rom::transport_dbg);
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    sealed_ = true;
    if (!transaction.is_read()) {
      transaction.set_response_status(tlm::TLM_COMMAND_ERROR_RESPONSE);
      return;
    }
    transaction.set_response_status(
        store_.Read(transaction.get_address(), Data(transaction))
            ? tlm::TLM_OK_RESPONSE
            : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    // The hint that tells an initiator DMI (below) is worth asking for.
    transaction.set_dmi_allowed(true);
  }

  // DMI: hand the initiator a pointer to the whole ROM, to read through
  // and not to write through. A CPU fetches its instructions this way.
  bool get_direct_mem_ptr(tlm::tlm_generic_payload&, tlm::tlm_dmi& dmi) {
    sealed_ = true;
    dmi.set_dmi_ptr(store_.Bytes().data());
    dmi.set_start_address(0);
    dmi.set_end_address(store_.Bytes().size() - 1);
    dmi.allow_read();
    return true;
  }

  // Debug transport: no simulated time. A read is a debugger looking, and
  // a write is how the ROM's bytes are put there. Returns the number of
  // bytes transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    // Too late: the chip is made.
    if (!transaction.is_read() && sealed_) return 0;
    const bool done =
        transaction.is_read()
            ? store_.Read(transaction.get_address(), Data(transaction))
            : store_.Write(transaction.get_address(), Data(transaction));
    return done ? transaction.get_data_length() : 0;
  }

  static std::span<std::uint8_t> Data(tlm::tlm_generic_payload& transaction) {
    return {transaction.get_data_ptr(), transaction.get_data_length()};
  }

  MemoryStore store_;
  // Set by the bus master's first transaction or request for direct memory
  // access. Debug writes are refused from then on.
  bool sealed_ = false;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_ROM_H_
