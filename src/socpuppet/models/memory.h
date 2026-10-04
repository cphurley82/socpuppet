#ifndef SOCPUPPET_MODELS_MEMORY_H_
#define SOCPUPPET_MODELS_MEMORY_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/memory_store.h"

namespace socpuppet {

// A flat RAM on the bus.
class Memory : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Memory> socket{"socket"};

  Memory(const sc_core::sc_module_name& name, std::size_t size)
      : sc_module(name), store_(size) {
    socket.register_b_transport(this, &Memory::b_transport);
    socket.register_get_direct_mem_ptr(this, &Memory::get_direct_mem_ptr);
    socket.register_transport_dbg(this, &Memory::transport_dbg);
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    transaction.set_response_status(Access(transaction)
                                        ? tlm::TLM_OK_RESPONSE
                                        : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    // The hint that tells an initiator DMI (below) is worth asking for.
    transaction.set_dmi_allowed(true);
  }

  // Debug transport: the same access with no simulated time and no side
  // effects. Returns the number of bytes transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return Access(transaction) ? transaction.get_data_length() : 0;
  }

  bool Access(tlm::tlm_generic_payload& transaction) {
    const std::span<std::uint8_t> data{transaction.get_data_ptr(),
                                       transaction.get_data_length()};
    return transaction.is_read()
               ? store_.Read(transaction.get_address(), data)
               : store_.Write(transaction.get_address(), data);
  }

  // DMI: hand the initiator a pointer to the whole memory, so it can read and
  // write without a transaction per access. This is what lets a CPU model
  // run fast.
  bool get_direct_mem_ptr(tlm::tlm_generic_payload&, tlm::tlm_dmi& dmi) {
    dmi.set_dmi_ptr(store_.Bytes().data());
    dmi.set_start_address(0);
    dmi.set_end_address(store_.Bytes().size() - 1);
    dmi.allow_read_write();
    return true;
  }

  MemoryStore store_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_MEMORY_H_
