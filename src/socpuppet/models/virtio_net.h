#ifndef SOCPUPPET_MODELS_VIRTIO_NET_H_
#define SOCPUPPET_MODELS_VIRTIO_NET_H_

#include <cstddef>
#include <utility>
#include <vector>

#include "socpuppet/core/virtio_net_logic.h"
#include "socpuppet/models/virtio_mmio.h"

namespace socpuppet {

// 🎭 The virtio network device on the bus (virtio 1.2, section 5.1), built
// from a name and its MAC address. Whoever holds the module is the far end
// of its wire: it sends frames in and reads the frames the driver sent.
class VirtioNet : public VirtioMmio<VirtioNetLogic> {
 public:
  using VirtioMmio::VirtioMmio;

  // Every frame the driver has sent, in order.
  const std::vector<VirtioNetLogic::Frame>& Received() const {
    return device().Transmitted();
  }

  // A frame comes in on the wire. It goes into a buffer the driver holds
  // out a delta cycle later, in a process of the device's own, since
  // whoever sends it may be a script between two runs.
  void Send(VirtioNetLogic::Frame frame) {
    device().Receive(std::move(frame));
    Nudge();
  }

  // How many frames that came in were dropped for want of room.
  std::size_t Dropped() const { return device().Dropped(); }
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_NET_H_
