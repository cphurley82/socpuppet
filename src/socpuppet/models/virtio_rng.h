#ifndef SOCPUPPET_MODELS_VIRTIO_RNG_H_
#define SOCPUPPET_MODELS_VIRTIO_RNG_H_

#include "socpuppet/core/virtio_rng_logic.h"
#include "socpuppet/models/virtio_mmio.h"

namespace socpuppet {

// The entropy device on the bus (virtio 1.2, section 5.4): built from a
// name and a seed.
using VirtioRng = VirtioMmio<VirtioRngLogic>;

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_VIRTIO_RNG_H_
