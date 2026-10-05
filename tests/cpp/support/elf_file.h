#ifndef TESTS_CPP_SUPPORT_ELF_FILE_H_
#define TESTS_CPP_SUPPORT_ELF_FILE_H_

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include <elfio/elfio.hpp>
#include <gtest/gtest.h>  // NOLINT(build/include_order)

// Writes small ELF images for tests to load, so that the tests need no
// toolchain. (ELF is the file format a linker produces: the program's bytes
// in segments, each with the address it belongs at, and the address
// execution starts from.)
struct ElfFile {
  struct Segment {
    // Where the bytes are to be loaded.
    std::uint64_t physical_address;
    // Where the program sees them once it runs, which differs only when it
    // turns on address translation.
    std::uint64_t virtual_address;
    std::string bytes;
    // A segment that is not loadable describes the program without being
    // part of it in memory: a note, for instance.
    bool loadable = true;
  };

  // 32 or 64: the word size the image is built for.
  unsigned xlen = 64;
  std::uint64_t entry = 0;
  std::vector<Segment> segments;

  // Writes the image to a file in the test's temporary directory and
  // returns where it is.
  std::string Write() const {
    ELFIO::elfio writer;
    writer.create(xlen == 64 ? ELFIO::ELFCLASS64 : ELFIO::ELFCLASS32,
                  ELFIO::ELFDATA2LSB);
    writer.set_type(ELFIO::ET_EXEC);
    writer.set_machine(ELFIO::EM_RISCV);
    writer.set_entry(entry);
    int number = 0;
    for (const Segment& each : segments) {
      ELFIO::section* section =
          writer.sections.add(".text" + std::to_string(number++));
      section->set_type(ELFIO::SHT_PROGBITS);
      section->set_flags(ELFIO::SHF_ALLOC | ELFIO::SHF_EXECINSTR);
      section->set_addr_align(4);
      section->set_data(each.bytes);
      ELFIO::segment* segment = writer.segments.add();
      segment->set_type(each.loadable ? ELFIO::PT_LOAD : ELFIO::PT_NOTE);
      segment->set_virtual_address(each.virtual_address);
      segment->set_physical_address(each.physical_address);
      segment->set_flags(ELFIO::PF_X | ELFIO::PF_R);
      segment->set_align(4);
      segment->add_section(section, section->get_addr_align());
    }
    const ::testing::TestInfo& test =
        *::testing::UnitTest::GetInstance()->current_test_info();
    const std::string path = ::testing::TempDir() + test.test_suite_name() +
                             "." + test.name() + ".elf";
    EXPECT_TRUE(writer.save(path)) << "Could not write " << path;
    return path;
  }
};

#endif  // TESTS_CPP_SUPPORT_ELF_FILE_H_
