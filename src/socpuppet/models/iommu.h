#ifndef SOCPUPPET_MODELS_IOMMU_H_
#define SOCPUPPET_MODELS_IOMMU_H_

#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// An IOMMU, as the RISC-V IOMMU specification describes it: what stands
// between devices and memory, so that each device reaches only the memory
// its operating system gave it. Every access a device makes comes in at
// `target`, marked with who sent it, its PCIe requester ID; it is looked up
// by that in a device directory, translated through that device's page
// tables, and goes out at `initiator`, which the IOMMU's own reads of its
// tables go out of too. An access that is not allowed, or that does not say
// who sent it, is refused. Firmware reaches its registers at `socket`.
//
// 🚧 Not built yet: the command and fault queues, and `irq`.
//
// The model is ours, written for VPV-Peripherals' rvi/ directory to be
// offered upstream (src/vpvper/rvi/iommu.h). This class is the adapter that
// fits it into a socpuppet platform, as the borrowed models' are.
class Iommu : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Iommu> socket{"socket"};
  tlm_utils::simple_target_socket<Iommu> target{"target"};
  tlm_utils::simple_initiator_socket<Iommu> initiator{"initiator"};
  sc_core::sc_out<bool> irq{"irq"};

  explicit Iommu(const sc_core::sc_module_name& name);
  ~Iommu() override;

 private:
  struct Model;

  void Configure(tlm::tlm_generic_payload& transaction,
                 sc_core::sc_time& delay);
  void Translate(tlm::tlm_generic_payload& transaction,
                 sc_core::sc_time& delay);

  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_IOMMU_H_
