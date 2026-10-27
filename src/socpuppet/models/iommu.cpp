#include "socpuppet/models/iommu.h"

#include <cstdint>
#include <memory>
#include <optional>

#include <rvi/gen/iommu_regs.h>
#include <rvi/iommu.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/models/borrowed_model.h"
#include "socpuppet/models/pcie_link.h"

namespace socpuppet {

namespace {

// Marks a transaction with the device it is from, as the model wants it,
// for as long as this is alive. The transaction is the caller's again
// afterwards, unmarked.
class AsFromDevice {
 public:
  AsFromDevice(tlm::tlm_generic_payload& transaction, std::uint32_t device)
      : transaction_(transaction), marker_(device) {
    transaction_.set_extension(&marker_);
  }
  ~AsFromDevice() { transaction_.clear_extension(&marker_); }
  AsFromDevice(const AsFromDevice&) = delete;
  AsFromDevice& operator=(const AsFromDevice&) = delete;

 private:
  tlm::tlm_generic_payload& transaction_;
  vpvper::rvi::iommu_device_id marker_;
};

}  // namespace

// The model and what it needs around it. Its reset is never asserted. What
// it sends out leaves by a socket of SCC's "loosely timed" kind, which
// binds only to its like, so it is taken here and passed on.
struct Iommu::Model {
  explicit Model(Iommu& owner) : owner_(owner) {
    iommu_.rst_i.bind(reset_tied_low_);
    iommu_.dma_o.bind(out_);
    iommu_.irq_o.bind(owner.irq);
    out_.register_b_transport(this, &Model::PassOn);
  }

  // A device's access, marked with the device it is from as the model
  // wants it, from its requester ID. One that does not say goes in
  // unmarked, and the model refuses it.
  void Translate(tlm::tlm_generic_payload& transaction,
                 sc_core::sc_time& delay) {
    const std::optional<std::uint16_t> requester = RequesterIdOf(transaction);
    if (!requester) {
      dma.Access(transaction, delay);
      return;
    }
    const AsFromDevice from_the_device{transaction, *requester};
    dma.Access(transaction, delay);
  }

 private:
  void PassOn(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    owner_.initiator->b_transport(transaction, delay);
  }

  Iommu& owner_;
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  PoweredOn<vpvper::rvi::iommu> iommu_{"iommu"};
  tlm_utils::simple_target_socket<Model, scc::LT> out_{"out"};

 public:
  BorrowedSocket registers{iommu_.socket, "to_registers"};
  BorrowedSocket dma{iommu_.dma_i, "to_dma"};
};

Iommu::Iommu(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>(*this)) {
  socket.register_b_transport(this, &Iommu::Configure);
  socket.register_transport_dbg(this, &Iommu::Look);
  target.register_b_transport(this, &Iommu::Translate);
}

Iommu::~Iommu() = default;

void Iommu::Configure(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay) {
  model_->registers.Access(transaction, delay);
}

// A debugger reads a register as firmware would, which has no side effects
// here: nothing happens on a read. A write would be firmware's, with all it
// sets going, so a debugger may not make one.
unsigned Iommu::Look(tlm::tlm_generic_payload& transaction) {
  if (!transaction.is_read()) return 0;
  return model_->registers.DebugAccess(transaction);
}

void Iommu::Translate(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay) {
  model_->Translate(transaction, delay);
}

}  // namespace socpuppet
