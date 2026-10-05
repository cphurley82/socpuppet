#ifndef SPIKES_ISS_QBOX_HARNESS_SIMPLE_ROUTER_H_
#define SPIKES_ISS_QBOX_HARNESS_SIMPLE_ROUTER_H_

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace spike {

// A router with nothing behind it but SystemC: one way in, and an address
// range for each way out. An access inside a range reaches that target at
// its offset from the start of the range.
//
// socpuppet's own router is SCC's. This one exists for the one candidate
// that cannot share a program with SCC (QBox brings its own copies of two
// libraries SCC bundles).
class SimpleRouter : public sc_core::sc_module {
 public:
  struct Range {
    std::uint64_t base;
    std::uint64_t size;
  };
  using Output = tlm_utils::simple_initiator_socket_tagged<SimpleRouter>;

  tlm_utils::simple_target_socket<SimpleRouter> target{"target"};

  SimpleRouter(const sc_core::sc_module_name& name, std::vector<Range> ranges)
      : sc_module(name), ranges_(std::move(ranges)) {
    target.register_b_transport(this, &SimpleRouter::b_transport);
    target.register_transport_dbg(this, &SimpleRouter::transport_dbg);
    target.register_get_direct_mem_ptr(this, &SimpleRouter::get_direct_mem_ptr);
    for (std::size_t index = 0; index < ranges_.size(); ++index) {
      const std::string output = "out" + std::to_string(index);
      outputs_.push_back(std::make_unique<Output>(output.c_str()));
      outputs_.back()->register_invalidate_direct_mem_ptr(
          this, &SimpleRouter::invalidate_direct_mem_ptr,
          static_cast<int>(index));
    }
  }

  Output& OutputAt(std::size_t index) { return *outputs_[index]; }

 private:
  static constexpr std::size_t kNowhere = static_cast<std::size_t>(-1);

  // Which output `address` belongs to.
  std::size_t Decode(std::uint64_t address) const {
    for (std::size_t index = 0; index < ranges_.size(); ++index) {
      if (address - ranges_[index].base < ranges_[index].size) return index;
    }
    return kNowhere;
  }

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    const std::uint64_t address = transaction.get_address();
    const std::size_t index = Decode(address);
    if (index == kNowhere) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
      return;
    }
    transaction.set_address(address - ranges_[index].base);
    (*outputs_[index])->b_transport(transaction, delay);
    transaction.set_address(address);
  }

  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    const std::uint64_t address = transaction.get_address();
    const std::size_t index = Decode(address);
    if (index == kNowhere) return 0;
    transaction.set_address(address - ranges_[index].base);
    const unsigned done = (*outputs_[index])->transport_dbg(transaction);
    transaction.set_address(address);
    return done;
  }

  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    const std::uint64_t address = transaction.get_address();
    const std::size_t index = Decode(address);
    if (index == kNowhere) return false;
    transaction.set_address(address - ranges_[index].base);
    const bool granted =
        (*outputs_[index])->get_direct_mem_ptr(transaction, dmi);
    transaction.set_address(address);
    // The target answers in its own addresses; the initiator needs ours.
    dmi.set_start_address(dmi.get_start_address() + ranges_[index].base);
    dmi.set_end_address(dmi.get_end_address() + ranges_[index].base);
    return granted;
  }

  void invalidate_direct_mem_ptr(int index, sc_dt::uint64 start,
                                 sc_dt::uint64 end) {
    const std::uint64_t base = ranges_[static_cast<std::size_t>(index)].base;
    target->invalidate_direct_mem_ptr(start + base, end + base);
  }

  std::vector<Range> ranges_;
  std::vector<std::unique_ptr<Output>> outputs_;
};

}  // namespace spike

#endif  // SPIKES_ISS_QBOX_HARNESS_SIMPLE_ROUTER_H_
