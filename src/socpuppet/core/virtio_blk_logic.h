#ifndef SOCPUPPET_CORE_VIRTIO_BLK_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_BLK_LOGIC_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>
#include <vector>

#include "socpuppet/core/block_store.h"
#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtqueue.h"

namespace socpuppet {

// 🎭 A virtio block device (virtio 1.2, section 5.2): a disk of 512-byte
// sectors that the driver reads and writes by request. Each request is
// one chain: a 16-byte header the device reads (the request's type and
// its first sector), the data (read by the device for a write, written
// by it for a read), and one status byte the device writes last.
//
// It stands for the disk QEMU's `virtio-blk-device` gives a guest, and
// leaves out everything a driver can do without: no multiple queues, no
// discard or write-zeroes, no size limits or geometry, and the disk is
// RAM, so a flush has nothing to do.
class VirtioBlkLogic : public VirtioDevice {
 public:
  static constexpr std::uint32_t kDeviceId = 2;
  // The request types, section 5.2.6.
  static constexpr std::uint32_t kTypeIn = 0;
  static constexpr std::uint32_t kTypeOut = 1;
  static constexpr std::uint32_t kTypeFlush = 4;
  static constexpr std::uint32_t kTypeGetId = 8;
  // The status byte.
  static constexpr std::uint8_t kStatusOk = 0;
  static constexpr std::uint8_t kStatusIoError = 1;
  static constexpr std::uint8_t kStatusUnsupported = 2;
  // VIRTIO_BLK_F_FLUSH: the driver may ask for a flush, and a write is
  // safe once one is answered. Offered because a flush is answered; with
  // no CONFIG_WCE beside it, Linux takes the disk for one with a
  // write-back cache and sends a flush where it needs one.
  static constexpr std::uint64_t kFeatureFlush = std::uint64_t{1} << 9U;
  // What GET_ID answers, in the 20 bytes the specification gives the
  // identity, padded with zeros. Every disk gives the same one, so two
  // disks under one Linux would share a name in /dev/disk/by-id.
  static constexpr std::string_view kIdentity = "socpuppet";

  explicit VirtioBlkLogic(std::uint64_t sectors) : store_(sectors) {
    StoreLittleEndian(sectors, std::span(config_));
  }

  std::uint32_t DeviceId() const override { return kDeviceId; }
  std::uint64_t Features() const override { return kFeatureFlush; }
  std::uint16_t QueueCount() const override { return 1; }
  // The configuration a driver needs with no features but FLUSH: the
  // capacity, in sectors, as a 64-bit number.
  std::span<const std::uint8_t> Config() const override { return config_; }
  // A request is answered as it is handed over, so none is in flight.
  void Reset() override {}

  void Handle(std::uint16_t /*queue*/, Virtqueue::Chain chain,
              Virtqueue& ring) override {
    const std::vector<std::uint8_t> request = ring.Read(chain);
    const std::size_t writable = chain.WritableBytes();
    if (request.size() < kHeaderBytes || writable == 0) {
      ring.Used(chain, 0);  // no header, or nowhere to say how it went
      return;
    }
    const std::span<const std::uint8_t> header =
        std::span(request).first(kHeaderBytes);
    const auto type = LoadLittleEndian<std::uint32_t>(header.subspan(0, 4));
    const auto sector = LoadLittleEndian<std::uint64_t>(header.subspan(8, 8));
    const std::span<const std::uint8_t> out =
        std::span(request).subspan(kHeaderBytes);
    // The status is the last byte the device may write, after the data.
    std::vector<std::uint8_t> answer(writable, 0);
    const std::span<std::uint8_t> in = std::span(answer).first(writable - 1);
    answer.back() = Answer(type, sector, out, in);
    ring.Used(chain, ring.Write(chain, answer));
  }

  // Puts `bytes` on the disk from its first sector on, the last sector
  // padded with zeros. Staying inside the disk is the caller's job.
  void Load(std::span<const std::uint8_t> bytes) {
    std::vector<std::uint8_t> sectors(RoundedUp(bytes.size()));
    std::ranges::copy(bytes, sectors.begin());
    store_.Write(0, sectors);
  }

  // Everything on the disk.
  std::vector<std::uint8_t> Contents() const {
    std::vector<std::uint8_t> bytes(Size());
    store_.Read(0, bytes);
    return bytes;
  }

  // How many bytes the disk holds.
  std::size_t Size() const { return store_.Blocks() * kSector; }

 private:
  static constexpr std::size_t kHeaderBytes = 16;
  static constexpr std::size_t kSector = BlockStore::kBlockSize;

  // Carries out one request: reads into `in` or writes from `out`, and
  // gives the status.
  std::uint8_t Answer(std::uint32_t type, std::uint64_t sector,
                      std::span<const std::uint8_t> out,
                      std::span<std::uint8_t> in) {
    switch (type) {
      case kTypeIn:
        if (!Fits(sector, in.size())) return kStatusIoError;
        store_.Read(sector, in);
        return kStatusOk;
      case kTypeOut:
        if (!Fits(sector, out.size())) return kStatusIoError;
        store_.Write(sector, out);
        return kStatusOk;
      case kTypeFlush:
        return kStatusOk;
      case kTypeGetId:
        std::ranges::copy(
            kIdentity.substr(0, std::min(in.size(), kIdentity.size())),
            in.begin());
        return kStatusOk;
      default:
        return kStatusUnsupported;
    }
  }

  // Whether `length` bytes from `sector` on are whole sectors on the
  // disk.
  bool Fits(std::uint64_t sector, std::size_t length) const {
    return length % kSector == 0 && sector <= store_.Blocks() &&
           length / kSector <= store_.Blocks() - sector;
  }

  static std::size_t RoundedUp(std::size_t length) {
    return (length + kSector - 1) / kSector * kSector;
  }

  RamBlockStore store_;
  std::array<std::uint8_t, 8> config_{};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_BLK_LOGIC_H_
