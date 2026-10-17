#ifndef SOCPUPPET_MODELS_VIRTIO_FS_H_
#define SOCPUPPET_MODELS_VIRTIO_FS_H_

#include <string_view>
#include <utility>

#include "socpuppet/core/virtio_fs_logic.h"
#include "socpuppet/models/virtio_mmio.h"

namespace socpuppet {

// 🎭 The virtio file system device on the bus (virtio 1.2, section 5.11),
// built from a name. Whoever holds the module names the share and says
// what serves it, before the run starts. The answerer is called from the
// device's own thread process, a request at a time.
class VirtioFs : public VirtioMmio<VirtioFsLogic> {
 public:
  using VirtioMmio::VirtioMmio;

  void SetTag(std::string_view tag) { device().SetTag(tag); }
  void SetAnswerer(VirtioFsLogic::Answerer answerer) {
    device().SetAnswerer(std::move(answerer));
  }
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_FS_H_
