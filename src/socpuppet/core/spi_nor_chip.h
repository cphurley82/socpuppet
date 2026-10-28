#ifndef SOCPUPPET_CORE_SPI_NOR_CHIP_H_
#define SOCPUPPET_CORE_SPI_NOR_CHIP_H_

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "socpuppet/core/spi_device.h"

namespace socpuppet {

// A NOR flash chip on an SPI bus, of Winbond's W25Q kind.
//
// `size` is how many bytes the chip holds: a power of two, as every W25Q
// part's is.
class SpiNorChip : public SpiDevice {
 public:
  explicit SpiNorChip(std::size_t size);

  void Select() override;
  std::uint8_t Transfer(std::uint8_t sent) override;
  void Deselect() override;

  // What the chip holds, a byte for each address, for those that reach it
  // without a frame: the window that maps it into memory, and a
  // debugger's writes.
  std::span<std::uint8_t> Bytes();

 private:
  // What the chip holds, a byte for each address.
  std::vector<std::uint8_t> bytes_;
  // The frame's first byte, which says what the rest of it is.
  std::uint8_t command_ = 0;
  // How many bytes of the frame have been sent so far.
  std::size_t position_ = 0;
  // The address a command was sent, gathered a byte at a time, then the
  // address of the next byte it reads, as sent: the chip ignores the bits
  // above its size when it uses it.
  std::size_t address_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_SPI_NOR_CHIP_H_
