#ifndef TESTS_CPP_SUPPORT_QBOX_FATES_H_
#define TESTS_CPP_SUPPORT_QBOX_FATES_H_

#include <array>
#include <cstddef>
#include <string>
#include <string_view>

// The hart's tests that the qbox_cpu does not pass, and why: what QEMU
// does that the specification allows and DBT-RISE does not, what the test
// assumes of DBT-RISE alone, and what QBox gets wrong (docs/upstream.md).
// On QBox each is skipped with its reason (kernel_test_main.cpp), so that
// a new failure stands out. docs/models/qbox-cpu.md sums them up.
struct QboxFate {
  // A test's full name as gtest knows it, or the start of one, ending "*".
  std::string_view tests;
  std::string_view reason;
};

inline constexpr std::string_view k64BitOnly = "QBox's CPU here is 64-bit only";
inline constexpr std::string_view kNanosecondAnInstruction =
    "QEMU counts a nanosecond an instruction, and the test counts "
    "DBT-RISE's hundred";
inline constexpr std::string_view kMisalignedInHardware =
    "QEMU loads and stores a word at an odd address itself, as the "
    "specification allows, where DBT-RISE traps";
inline constexpr std::string_view kMisalignedAtomic =
    "QEMU raises a load's cause for an atomic at an odd address, where the "
    "specification says a store's (docs/upstream.md)";
inline constexpr std::string_view kAccessedAndDirtyInHardware =
    "QEMU sets a page's accessed and dirty bits itself, as the "
    "specification allows, where DBT-RISE takes a page fault";
inline constexpr std::string_view kQemusPaging =
    "QEMU keeps an address-space identifier, and has Sv48 and Sv57, which "
    "socpuppet's patch takes out of DBT-RISE";
inline constexpr std::string_view kAtomicsSpin =
    "an atomic to memory without direct access never completes: QEMU asks "
    "for it to be run again on its own, and QBox's coroutine never does "
    "(docs/upstream.md)";

inline constexpr std::array kQboxFates{
    QboxFate{"WhenXlenIs32.*", k64BitOnly},
    QboxFate{"WhenA32BitCpusTimeIsConnectedToItsTimer.*", k64BitOnly},
    QboxFate{"WhenA32BitCpuAheadOfTheClockSetsItsCompareValueInThreeWrites.*",
             k64BitOnly},
    QboxFate{"WhenA64BitAndA32BitCpuShareASimulation.*", k64BitOnly},
    QboxFate{"WhenACpusTimeIsConnectedToItsTimer."
             "TheTimeRegisterReadsOneTickBehind*",
             kNanosecondAnInstruction},
    QboxFate{"WhenA64BitCpuAheadOfTheClockSetsItsCompareValueInOneWrite.*",
             kNanosecondAnInstruction},
    QboxFate{"WhenAMemoryWithdrawsDirectAccess.*",
             "QEMU counts a nanosecond an instruction, so the test's loop "
             "has ended by the time it withdraws access"},
    QboxFate{"WhenUserModeIsAllowedTheTimeRegisterOnACpuConnectedToItsTimer.*",
             "the program sleeps in user mode, where QEMU makes wfi an "
             "illegal instruction, as the specification allows a hart with "
             "supervisor mode to"},
    QboxFate{"EachUse/WhenSupervisorModeUsesAWordAtAnOddAddress.*/ALoad",
             kMisalignedInHardware},
    QboxFate{"EachUse/WhenSupervisorModeUsesAWordAtAnOddAddress.*/AStore",
             kMisalignedInHardware},
    QboxFate{"EachUse/WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIs"
             "HandedDown.*/ALoad",
             kMisalignedInHardware},
    QboxFate{"EachUse/WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIs"
             "HandedDown.*/AStore",
             kMisalignedInHardware},
    QboxFate{"WhenAHandlerMakesTheStoreThatAHartRefusedAtAnOddAddress.*",
             kMisalignedInHardware},
    QboxFate{"EachUse/WhenSupervisorModeUsesAWordAtAnOddAddress.*/AnAtomicSum",
             kMisalignedAtomic},
    QboxFate{"EachUse/WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIs"
             "HandedDown.*/AnAtomicSum",
             kMisalignedAtomic},
    QboxFate{"EachWay/WhenSupervisorModeUsesAPageInAWayItsEntryDoesNotAllow."
             "*/ALoadFromAPageNotMarkedAccessed",
             kAccessedAndDirtyInHardware},
    QboxFate{"EachWay/WhenSupervisorModeUsesAPageInAWayItsEntryDoesNotAllow."
             "*/AStoreToAPageNotMarkedDirty",
             kAccessedAndDirtyInHardware},
    QboxFate{"WhenSupervisorModeStoresToAPageNotMarkedDirtyThatItHasJust"
             "LoadedFrom.*",
             kAccessedAndDirtyInHardware},
    QboxFate{"WhenSatpIsWrittenWithAnAddressSpaceIdentifier.*", kQemusPaging},
    QboxFate{"EachKind/WhenSatpIsWrittenWithAKindOfPagingTheHartHasNot.*/Sv48",
             kQemusPaging},
    QboxFate{"EachKind/WhenSatpIsWrittenWithAKindOfPagingTheHartHasNot.*/Sv57",
             kQemusPaging},
    QboxFate{"EitherWay/WhenAStoreConditionalFollowsALoadReservedOfItsCell."
             "*OverTheBus",
             kAtomicsSpin},
    QboxFate{"EachReason/WhenAStoreConditionalFindsNoReservationOnItsCell."
             "*OverTheBus",
             kAtomicsSpin},
    QboxFate{"EachOperation/WhenAProgramUsesAnAtomicMemoryOperation."
             "*OverTheBus",
             kAtomicsSpin},
    QboxFate{"TheThreeOfEachMode/WhenACpuWithNoImsicWritesARegisterAnImsic"
             "WouldAnswer.*/Miselect",
             "QEMU keeps miselect itself whenever it has the registers of "
             "the Advanced Interrupt Architecture, which a qbox_cpu always "
             "asks for"},
    QboxFate{"TheThreeOfEachMode/WhenACpuWithNoImsicWritesARegisterAnImsic"
             "WouldAnswer.*/Siselect",
             "QEMU keeps siselect itself whenever it has the registers of "
             "the Advanced Interrupt Architecture, which a qbox_cpu always "
             "asks for"},
    QboxFate{"TheThree/WhenACpuWithAnImsicAndNoSupervisorModeWritesARegister"
             "OfThatModes.*",
             "QBox's CPU always has supervisor mode"},
    QboxFate{"WhenAResetPulseComesAndGoesWhileABusyCpuIsAheadOfTheClock.*",
             "QBox does not take a reset that comes and goes while a busy "
             "CPU is ahead of the clock (docs/upstream.md)"},
};

// Whether `name` is matched by `pattern`, in which each "*" stands for any
// run of characters, as in gtest's own filters.
constexpr bool MatchesFate(std::string_view name, std::string_view pattern) {
  if (pattern.empty()) return name.empty();
  if (pattern.front() == '*') {
    for (std::size_t skip = 0; skip <= name.size(); ++skip) {
      if (MatchesFate(name.substr(skip), pattern.substr(1))) return true;
    }
    return false;
  }
  return !name.empty() && name.front() == pattern.front() &&
         MatchesFate(name.substr(1), pattern.substr(1));
}

// Why the qbox_cpu does not pass the test called `name`, or nothing if it
// does. Each "*" in `name` is taken as itself.
constexpr std::string_view WhyQboxFails(std::string_view name) {
  for (const QboxFate& fate : kQboxFates) {
    if (MatchesFate(name, fate.tests)) return fate.reason;
  }
  return {};
}

// Every fate's pattern, as the negative part of a gtest filter
// ("-one:two"), so that a run of many tests leaves them out.
inline std::string AllQboxFates() {
  std::string filter = "-";
  for (const QboxFate& fate : kQboxFates) {
    if (filter.size() > 1) filter += ':';
    filter += fate.tests;
  }
  return filter;
}

#endif  // TESTS_CPP_SUPPORT_QBOX_FATES_H_
