#ifndef SOCPUPPET_MODELS_VIRTIO_MMIO_H_
#define SOCPUPPET_MODELS_VIRTIO_MMIO_H_

#include <concepts>
#include <utility>

#include <systemc>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtio_mmio_logic.h"
#include "socpuppet/models/command_device.h"
#include "socpuppet/models/socket_memory.h"

namespace socpuppet {

// 🎭 A virtio device on the bus, behind the virtio-mmio transport: the
// SystemC shell that every virtio device of socpuppet's shares, around a
// `Device`, the logic of one kind of device (virtio_device.h). The
// transport's registers and virtqueues are VirtioMmioLogic's.
//
// `cpu` is the register block and `irq` its interrupt line, as
// CommandDevice has them: a write to a register returns at once, and the
// device goes and looks at its queues a delta cycle later, so that its
// reads of the driver's memory never happen inside the driver's own
// access. `dma` is how it reaches that memory.
template <std::derived_from<VirtioDevice> Device>
class VirtioMmio : public CommandDevice<VirtioMmioLogic> {
 public:
  tlm_utils::simple_initiator_socket<VirtioMmio> dma{"dma"};

  // `args` build the device: a seed, a size, whatever its kind takes.
  template <typename... Args>
  explicit VirtioMmio(const sc_core::sc_module_name& name, Args&&... args)
      : CommandDevice(name, transport_), device_(std::forward<Args>(args)...) {}

 protected:
  // The device behind the transport, for a shell that is its far end.
  Device& device() { return device_; }
  const Device& device() const { return device_; }

 private:
  using Initiator = tlm_utils::simple_initiator_socket<VirtioMmio>;

  // The driver's memory, as the transport reaches it.
  SocketMemory<Initiator> memory_{dma};
  // The device comes before the transport: the transport asks it how many
  // queues it has when it is built.
  Device device_;
  VirtioMmioLogic transport_{device_, memory_};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_MMIO_H_
