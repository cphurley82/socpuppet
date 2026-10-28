#ifndef SOCPUPPET_CORE_SPI_DEVICE_H_
#define SOCPUPPET_CORE_SPI_DEVICE_H_

#include <cstdint>

namespace socpuppet {

// A device on an SPI bus, as its controller sees it.
//
// 🎓 SPI is a serial bus of four wires: a clock, a wire out and a wire back,
// and a chip select for each device, which the controller pulls low to
// talk to that one. Every clock moves a bit each way at once, so a byte
// out is always a byte back, whether the device had anything to say or
// not. A frame is everything between pulling the select low and letting
// it go: a command and its address, then data.
//
// Every call comes from a thread process of the controller's own, never
// from the thread of whoever wrote the controller's registers, so a device
// may wait in any of them. Time a device waits in Transfer() is time on
// the bus. Deselect() may come a delta cycle after the line rises, and
// always before a chip is selected again.
class SpiDevice {
 public:
  virtual ~SpiDevice() = default;

  // The controller has pulled this device's chip select low: a frame
  // starts.
  virtual void Select() = 0;
  // One byte each way: `sent` from the controller, and what the device
  // answers in the same eight clocks.
  virtual std::uint8_t Transfer(std::uint8_t sent) = 0;
  // The chip select has gone high again: the frame is over.
  virtual void Deselect() = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_SPI_DEVICE_H_
