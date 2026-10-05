#include "socpuppet/core/elf_image.h"

#include <cstddef>
#include <stdexcept>
#include <string>

#include <elfio/elfio.hpp>

namespace socpuppet {

// The parsing is ELFIO's.
ElfImage ReadElfImage(const std::string& path) {
  ELFIO::elfio reader;
  if (!reader.load(path)) {
    throw std::invalid_argument(
        "\"" + path +
        "\" could not be read as an ELF image. Check that the file exists "
        "and is the linked program (often called zephyr.elf), not a flat "
        "binary.");
  }
  ElfImage image;
  image.xlen = reader.get_class() == ELFIO::ELFCLASS64 ? 64 : 32;
  image.entry = reader.get_entry();
  for (const auto& segment : reader.segments) {
    if (segment->get_type() != ELFIO::PT_LOAD) continue;
    if (segment->get_file_size() == 0) continue;
    const auto* data = reinterpret_cast<const std::byte*>(segment->get_data());
    image.segments.push_back(
        {.address = segment->get_physical_address(),
         .bytes = {data, data + segment->get_file_size()}});
  }
  return image;
}

}  // namespace socpuppet
