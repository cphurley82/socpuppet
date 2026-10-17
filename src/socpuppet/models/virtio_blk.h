#ifndef SOCPUPPET_MODELS_VIRTIO_BLK_H_
#define SOCPUPPET_MODELS_VIRTIO_BLK_H_

#include <cstddef>
#include <cstdint>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

#include "socpuppet/core/virtio_blk_logic.h"
#include "socpuppet/models/virtio_mmio.h"

namespace socpuppet {

// 🎭 The virtio block device on the bus (virtio 1.2, section 5.2), built
// from a name and the disk's size in 512-byte sectors. Whoever holds the
// module can put a disk image on it before a run and look at the disk
// after one.
class VirtioBlk : public VirtioMmio<VirtioBlkLogic> {
 public:
  using VirtioMmio::VirtioMmio;

  // Puts `image` on the disk from its first sector on. An image larger
  // than the disk is refused with std::invalid_argument, and the disk is
  // left as it was.
  void Load(std::span<const std::uint8_t> image) {
    if (image.size() > Size()) {
      throw std::invalid_argument(
          "The image is " + std::to_string(image.size()) +
          " bytes, and the disk " + std::string(name()) + " holds " +
          std::to_string(Size()) +
          ". Give the disk more blocks, or make the image smaller.");
    }
    device().Load(image);
  }
  // Everything on the disk.
  std::vector<std::uint8_t> Contents() const { return device().Contents(); }
  // How many bytes the disk holds.
  std::size_t Size() const { return device().Size(); }
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_BLK_H_
