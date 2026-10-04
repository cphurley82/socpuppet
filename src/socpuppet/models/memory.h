#pragma once

#include <cstddef>
#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/memory_store.h"

namespace socpuppet {

// A flat RAM on the bus. peek32 reads directly, without a bus transaction,
// in host byte order.
class Memory : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Memory> socket{"socket"};

  Memory(const sc_core::sc_module_name& name, std::size_t size)
      : sc_module(name), store_(size) {
    socket.register_b_transport(this, &Memory::b_transport);
    socket.register_get_direct_mem_ptr(this, &Memory::get_direct_mem_ptr);
    socket.register_transport_dbg(this, &Memory::transport_dbg);
  }

  std::uint32_t peek32(std::uint64_t address) const {
    std::uint32_t value = 0;
    store_.read(address, {reinterpret_cast<std::uint8_t*>(&value), sizeof value});
    return value;
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    transaction.set_response_status(access(transaction) ? tlm::TLM_OK_RESPONSE
                                                        : tlm::TLM_ADDRESS_ERROR_RESPONSE);
  }

  // Debug transport: the same access with no simulated time and no side
  // effects. Returns the number of bytes transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return access(transaction) ? transaction.get_data_length() : 0;
  }

  bool access(tlm::tlm_generic_payload& transaction) {
    const std::span<std::uint8_t> data{transaction.get_data_ptr(),
                                       transaction.get_data_length()};
    return transaction.is_read() ? store_.read(transaction.get_address(), data)
                                 : store_.write(transaction.get_address(), data);
  }

  // DMI: hand the initiator a pointer to the whole memory, so it can read and
  // write without a transaction per access. This is what lets a CPU model
  // run fast.
  bool get_direct_mem_ptr(tlm::tlm_generic_payload&, tlm::tlm_dmi& dmi) {
    dmi.set_dmi_ptr(store_.bytes().data());
    dmi.set_start_address(0);
    dmi.set_end_address(store_.bytes().size() - 1);
    dmi.allow_read_write();
    return true;
  }

  MemoryStore store_;
};

}  // namespace socpuppet
