#ifndef SPIKES_ISS_INHOUSE_INHOUSE_CPU_H_
#define SPIKES_ISS_INHOUSE_INHOUSE_CPU_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <span>
#include <utility>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

#include "spikes/iss/inhouse/hart.h"

namespace spike {

// The in-house hart, fitted to the spike's CPU slot. This is everything
// the hart needs from a simulator, and it is the same list every wrapper in
// this spike had to supply:
//   - a thread to run on, which hands over to the rest of the platform
//     once it has run a quantum ahead;
//   - memory accesses turned into transactions, or into reads and writes
//     through a DMI pointer when the target offers one;
//   - reset, done by SystemC's own asynchronous reset of the thread;
//   - the interrupt line.
//
// `Reg` is std::uint32_t or std::uint64_t.
template <typename Reg>
class InhouseCpu : public sc_core::sc_module, private inhouse::Bus {
 public:
  tlm_utils::simple_initiator_socket<InhouseCpu> socket{"socket"};
  sc_core::sc_in<bool> irq{"irq"};
  sc_core::sc_in<bool> reset{"reset"};

  InhouseCpu(const sc_core::sc_module_name& name, std::uint64_t reset_pc)
      : sc_module(name), reset_pc_(static_cast<Reg>(reset_pc)) {
    socket.register_invalidate_direct_mem_ptr(
        this, &InhouseCpu::invalidate_direct_mem_ptr);
    SC_THREAD(Run);
    async_reset_signal_is(reset, true);
    SC_METHOD(OnInterruptLine);
    sensitive << irq;
    dont_initialize();
  }

  void before_end_of_elaboration() override {
    if (irq.size() == 0) irq.bind(tied_low_);
    if (reset.size() == 0) reset.bind(tied_low_);
  }

 private:
  // One instruction takes this long: a 10 MHz clock, which is what
  // Zephyr's boards for QEMU are told they have.
  static sc_core::sc_time Cycle() { return {100, sc_core::SC_NS}; }

  // Starts here at the beginning of the simulation, and again each time
  // the reset line goes high: SystemC abandons whatever the thread was
  // doing and calls this afresh.
  void Run() {
    // Once only: let a reset line that is driven high from time zero take
    // its value before we look at it.
    if (!std::exchange(settled_, true)) wait(sc_core::SC_ZERO_TIME);
    if (reset.read()) wait(reset.negedge_event());
    hart_.Reset(reset_pc_);
    hart_.SetInterruptPending(inhouse::kMachineExternalInterrupt, irq.read());
    for (;;) {
      if (hart_.Asleep()) {
        wait(interrupt_changed_);
        continue;
      }
      // Run ahead of the kernel's clock by up to a quantum, then let
      // simulated time catch up with what was executed.
      const sc_core::sc_time quantum =
          tlm::tlm_global_quantum::instance().get();
      const std::uint64_t budget =
          std::max<std::uint64_t>(1, quantum.value() / Cycle().value());
      retired_at_sync_ = hart_.InstructionsRetired();
      const std::uint64_t executed = hart_.Run(budget);
      wait(Cycle() * static_cast<double>(executed) + bus_delay_);
      bus_delay_ = sc_core::SC_ZERO_TIME;
    }
  }

  void OnInterruptLine() {
    hart_.SetInterruptPending(inhouse::kMachineExternalInterrupt, irq.read());
    interrupt_changed_.notify();
  }

  // ---- inhouse::Bus --------------------------------------------------------

  bool Read(std::uint64_t address, std::span<std::byte> data) override {
    if (std::byte* direct = DirectPointer(address, data.size())) {
      std::memcpy(data.data(), direct, data.size());
      return true;
    }
    return Transport(tlm::TLM_READ_COMMAND, address, data.data(), data.size());
  }

  bool Write(std::uint64_t address, std::span<const std::byte> data) override {
    if (std::byte* direct = DirectPointer(address, data.size())) {
      std::memcpy(direct, data.data(), data.size());
      return true;
    }
    return Transport(tlm::TLM_WRITE_COMMAND, address,
                     const_cast<std::byte*>(data.data()), data.size());
  }

  // Where `size` bytes at `address` are, if they are inside the region the
  // CPU has direct memory access (DMI) to.
  std::byte* DirectPointer(std::uint64_t address, std::size_t size) {
    const std::uint64_t offset = address - dmi_start_;
    if (offset >= dmi_size_ || size > dmi_size_ - offset) return nullptr;
    return dmi_pointer_ + offset;
  }

  bool Transport(tlm::tlm_command command, std::uint64_t address,
                 std::byte* data, std::size_t size) {
    tlm::tlm_generic_payload transaction;
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(reinterpret_cast<unsigned char*>(data));
    transaction.set_data_length(static_cast<unsigned>(size));
    transaction.set_streaming_width(static_cast<unsigned>(size));
    // How far ahead of the kernel's clock this access happens.
    const sc_core::sc_time ahead =
        Cycle() * static_cast<double>(hart_.InstructionsRetired() -
                                      retired_at_sync_) +
        bus_delay_;
    sc_core::sc_time delay = ahead;
    socket->b_transport(transaction, delay);
    // Whatever the target added is time the access took.
    bus_delay_ += delay - ahead;
    if (transaction.is_dmi_allowed()) RequestDirectAccess(address);
    return transaction.is_response_ok();
  }

  // The target said DMI is worth asking for: ask, and remember the region
  // it grants.
  void RequestDirectAccess(std::uint64_t address) {
    tlm::tlm_generic_payload request;
    request.set_address(address);
    tlm::tlm_dmi dmi;
    if (!socket->get_direct_mem_ptr(request, dmi)) return;
    if (!dmi.is_read_write_allowed()) return;
    dmi_pointer_ = reinterpret_cast<std::byte*>(dmi.get_dmi_ptr());
    dmi_start_ = dmi.get_start_address();
    dmi_size_ = dmi.get_end_address() - dmi.get_start_address() + 1;
  }

  // The target takes its pointer back.
  void invalidate_direct_mem_ptr(sc_dt::uint64 start, sc_dt::uint64 end) {
    if (dmi_size_ != 0 && start < dmi_start_ + dmi_size_ && end >= dmi_start_) {
      dmi_size_ = 0;
    }
  }

  Reg reset_pc_;
  bool settled_ = false;
  inhouse::Hart<Reg> hart_{*this};
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  sc_core::sc_event interrupt_changed_;
  // The hart's instruction count when the kernel's clock last caught up.
  std::uint64_t retired_at_sync_ = 0;
  // Time that targets added to transactions since then.
  sc_core::sc_time bus_delay_;
  std::byte* dmi_pointer_ = nullptr;
  std::uint64_t dmi_start_ = 0;
  std::uint64_t dmi_size_ = 0;
};

}  // namespace spike

#endif  // SPIKES_ISS_INHOUSE_INHOUSE_CPU_H_
