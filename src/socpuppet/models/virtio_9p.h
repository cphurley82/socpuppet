#ifndef SOCPUPPET_MODELS_VIRTIO_9P_H_
#define SOCPUPPET_MODELS_VIRTIO_9P_H_

#include <string_view>
#include <utility>

#include "socpuppet/core/virtio_9p_logic.h"
#include "socpuppet/models/virtio_mmio.h"

namespace socpuppet {

// 🎭 The virtio 9P transport on the bus (device kind 9), built from a
// name. Whoever holds the module names the share and says what serves
// it, before the run starts. The answerer is called from the device's own
// thread process, a message at a time.
class Virtio9p : public VirtioMmio<Virtio9pLogic> {
 public:
  using VirtioMmio::VirtioMmio;

  void SetTag(std::string_view tag) { DeviceLogic().SetTag(tag); }
  void SetAnswerer(Virtio9pLogic::Answerer answerer) {
    DeviceLogic().SetAnswerer(std::move(answerer));
  }
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_9P_H_
