#ifndef SOCPUPPET_CORE_BLOCK_STORE_H_
#define SOCPUPPET_CORE_BLOCK_STORE_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <unordered_map>
#include <vector>

namespace socpuppet {

// What a drive holds: numbered blocks of 512 bytes, the size a disk has
// had since the floppy. A controller model reads and writes them here, and
// what is behind (RAM, or one day a file) is the store's business.
//
// Both calls take whole blocks, from block `first` on, as many as the span
// holds. Staying inside the store is the caller's job.
class BlockStore {
 public:
  static constexpr std::size_t kBlockSize = 512;

  virtual ~BlockStore() = default;

  // How many blocks the store holds.
  virtual std::uint64_t Blocks() const = 0;
  virtual void Read(std::uint64_t first, std::span<std::uint8_t> out) const = 0;
  virtual void Write(std::uint64_t first, std::span<const std::uint8_t> in) = 0;
};

// A drive kept in RAM, all zeros until written. Only what has been written
// takes any memory, so a drive may be far larger than the machine the
// simulation runs on.
class RamBlockStore final : public BlockStore {
 public:
  explicit RamBlockStore(std::uint64_t blocks) : blocks_(blocks) {}

  std::uint64_t Blocks() const override { return blocks_; }

  void Read(std::uint64_t first, std::span<std::uint8_t> out) const override {
    for (std::size_t done = 0; done < out.size(); done += kBlockSize) {
      const std::uint64_t block = first + (done / kBlockSize);
      const std::span<std::uint8_t> to = out.subspan(done, kBlockSize);
      const auto piece = pieces_.find(block / kBlocksPerPiece);
      if (piece == pieces_.end()) {
        std::ranges::fill(to, std::uint8_t{0});
      } else {
        std::ranges::copy(
            std::span{piece->second}.subspan(OffsetInPiece(block), kBlockSize),
            to.begin());
      }
    }
  }

  void Write(std::uint64_t first, std::span<const std::uint8_t> in) override {
    for (std::size_t done = 0; done < in.size(); done += kBlockSize) {
      const std::uint64_t block = first + (done / kBlockSize);
      std::vector<std::uint8_t>& piece = pieces_[block / kBlocksPerPiece];
      // A piece is created on the first write into it, as zeros.
      piece.resize(kBlocksPerPiece * kBlockSize);
      std::ranges::copy(in.subspan(done, kBlockSize),
                        std::span{piece}.subspan(OffsetInPiece(block)).begin());
    }
  }

 private:
  // The drive is kept in pieces of this many blocks (64 KiB), each of
  // which exists once any block in it has been written.
  static constexpr std::uint64_t kBlocksPerPiece = 128;

  // Where a block's bytes start inside the piece that holds it.
  static std::size_t OffsetInPiece(std::uint64_t block) {
    return (block % kBlocksPerPiece) * kBlockSize;
  }

  std::uint64_t blocks_;
  std::unordered_map<std::uint64_t, std::vector<std::uint8_t>> pieces_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_BLOCK_STORE_H_
