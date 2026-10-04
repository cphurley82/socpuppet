#ifndef SPIKES_ISS_RISCV_VP_RISCV_VP_CPU_H_
#define SPIKES_ISS_RISCV_VP_RISCV_VP_CPU_H_

#include <cstdint>
#include <memory>
#include <optional>
#include <utility>

#include <core/common/bus_lock_if.h>
#include <core/common/clint_if.h>
#include <core/common/dmi.h>
#include <core/common/irq_if.h>
#include <core/rv32/iss.h>
#include <core/rv32/mem.h>
#include <core/rv32/mmu.h>
#include <core/rv64/iss.h>
#include <core/rv64/mem.h>
#include <core/rv64/mmu.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace spike {

// The pieces riscv-vp builds a core from, for each word size. They have the
// same names in two namespaces and nearly the same constructors.
struct RiscvVp64 {
  using Iss = rv64::ISS;
  using Mmu = rv64::MMU;
  using Memory = rv64::CombinedMemoryInterface;
  using Fetch = rv64::InstrMemoryProxy;
  using Address = std::uint64_t;
  static std::unique_ptr<Memory> MakeMemory(Iss& iss, Mmu& mmu) {
    return std::make_unique<Memory>("memory", iss, mmu);
  }
};
struct RiscvVp32 {
  using Iss = rv32::ISS;
  using Mmu = rv32::MMU;
  using Memory = rv32::CombinedMemoryInterface;
  using Fetch = rv32::InstrMemoryProxy;
  using Address = std::uint32_t;
  static std::unique_ptr<Memory> MakeMemory(Iss& iss, Mmu& mmu) {
    return std::make_unique<Memory>("memory", iss, &mmu);
  }
};

// The lock that makes a load-reserved and store-conditional pair atomic
// between harts that share a bus. Each of our CPUs is alone on its bus, so
// there is never anyone to wait for.
class UncontendedBusLock : public bus_lock_if {
 public:
  void lock(unsigned) override { locked_ = true; }
  void unlock(unsigned) override { locked_ = false; }
  bool is_locked() override { return locked_; }
  bool is_locked(unsigned) override { return locked_; }
  void wait_until_unlocked() override {}

 private:
  bool locked_ = false;
};

// riscv-vp's ISS (University of Bremen), fitted to the spike's CPU slot.
//
// riscv-vp gives us an ISS as a plain C++ object and the piece that turns
// its memory accesses into TLM transactions. Everything a platform's
// main() does around those in riscv-vp is done here instead:
//   - The thread the ISS runs on, which riscv-vp ends by stopping the
//     simulation.
//   - Reset, which the ISS has no notion of. The thread is reset by
//     SystemC itself when the reset line goes high, and builds a fresh ISS
//     when it starts again.
//   - DMI. The ISS takes a raw pointer to RAM, handed over before it
//     starts. Here the pointer is asked for the TLM way first.
//   - The timer, which the ISS expects to ask for the time, and the bus
//     lock it uses for atomic instructions.
template <typename Parts>
class RiscvVpCpu : public sc_core::sc_module, private clint_if {
 public:
  tlm_utils::simple_initiator_socket<RiscvVpCpu> socket{"socket"};
  sc_core::sc_in<bool> irq{"irq"};
  sc_core::sc_in<bool> reset{"reset"};

  RiscvVpCpu(const sc_core::sc_module_name& name, std::uint64_t reset_pc)
      : sc_module(name), reset_pc_(reset_pc) {
    iss_.emplace(0);
    mmu_.emplace(*iss_);
    memory_ = Parts::MakeMemory(*iss_, *mmu_);
    memory_->bus_lock = std::make_shared<UncontendedBusLock>();
    memory_->isock.bind(from_core_);
    from_core_.register_b_transport(this, &RiscvVpCpu::b_transport);
    from_core_.register_transport_dbg(this, &RiscvVpCpu::transport_dbg);

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
  // Starts here at the beginning of the simulation, and again each time
  // the reset line goes high: SystemC abandons whatever the thread was
  // doing and calls this afresh.
  void Run() {
    // Once only: let a reset line that is driven high from time zero take
    // its value before we look at it.
    if (!std::exchange(settled_, true)) wait(sc_core::SC_ZERO_TIME);
    if (reset.read()) wait(reset.negedge_event());
    StartAfresh();
    iss_->run();
  }

  // Replaces the ISS with a new one, in the same place, so that the pieces
  // that refer to it still do.
  void StartAfresh() {
    fetch_.reset();
    iss_.emplace(0);
    mmu_.emplace(*iss_);
    memory_->dmi_ranges.clear();

    tlm::tlm_generic_payload request;
    request.set_address(reset_pc_);
    tlm::tlm_dmi dmi;
    if (socket->get_direct_mem_ptr(request, dmi)) {
      const MemoryDMI ram = MemoryDMI::create_start_size_mapping(
          dmi.get_dmi_ptr(), dmi.get_start_address(),
          dmi.get_end_address() - dmi.get_start_address() + 1);
      memory_->dmi_ranges.push_back(ram);
      fetch_.emplace(ram, *iss_);
    }
    const auto entry = static_cast<typename Parts::Address>(reset_pc_);
    if (fetch_) {
      iss_->init(&*fetch_, memory_.get(), this, entry, 0);
    } else {
      iss_->init(memory_.get(), memory_.get(), this, entry, 0);
    }
  }

  void OnInterruptLine() {
    if (irq.read()) {
      iss_->trigger_external_interrupt(MachineMode);
    } else {
      iss_->clear_external_interrupt(MachineMode);
    }
  }

  // The machine timer's count, at the 10 MHz Zephyr's boards for QEMU are
  // told it ticks at.
  std::uint64_t update_and_get_mtime() override {
    return sc_core::sc_time_stamp().value() /
           sc_core::sc_time(100, sc_core::SC_NS).value();
  }

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    socket->b_transport(transaction, delay);
  }
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return socket->transport_dbg(transaction);
  }

  std::uint64_t reset_pc_;
  bool settled_ = false;
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  tlm_utils::simple_target_socket<RiscvVpCpu> from_core_{"from_core"};
  std::optional<typename Parts::Iss> iss_;
  std::optional<typename Parts::Mmu> mmu_;
  std::unique_ptr<typename Parts::Memory> memory_;
  std::optional<typename Parts::Fetch> fetch_;
};

}  // namespace spike

#endif  // SPIKES_ISS_RISCV_VP_RISCV_VP_CPU_H_
