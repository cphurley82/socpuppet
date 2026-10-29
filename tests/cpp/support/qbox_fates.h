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
inline constexpr std::string_view k128NanosecondsAnInstruction =
    "QEMU counts 128 ns an instruction, and the test counts DBT-RISE's "
    "100";
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
    QboxFate{.tests = "WhenXlenIs32.*", .reason = k64BitOnly},
    QboxFate{
        .tests = "WhenA32BitCpusTimeIsConnectedToItsTimer.*",
        .reason = k64BitOnly,
    },
    QboxFate{
        .tests =
            "WhenA32BitCpuAheadOfTheClockSetsItsCompareValueInThreeWrites.*",
        .reason = k64BitOnly,
    },
    QboxFate{
        .tests = "WhenA64BitAndA32BitCpuShareASimulation.*",
        .reason = k64BitOnly,
    },
    QboxFate{
        .tests = "WhenACpusTimeIsConnectedToItsTimer."
                 "TheTimeRegisterReadsOneTickBehind*",
        .reason = k128NanosecondsAnInstruction,
    },
    QboxFate{
        .tests = "WhenAMemoryWithdrawsDirectAccess.*",
        .reason = k128NanosecondsAnInstruction,
    },
    QboxFate{
        .tests =
            "WhenUserModeIsAllowedTheTimeRegisterOnACpuConnectedToItsTimer.*",
        .reason =
            "the program sleeps in user mode, where QEMU makes wfi an "
            "illegal instruction, as the specification allows a hart with "
            "supervisor mode to",
    },
    QboxFate{
        .tests = "EachUse/WhenSupervisorModeUsesAWordAtAnOddAddress.*/ALoad",
        .reason = kMisalignedInHardware,
    },
    QboxFate{
        .tests = "EachUse/WhenSupervisorModeUsesAWordAtAnOddAddress.*/AStore",
        .reason = kMisalignedInHardware,
    },
    QboxFate{
        .tests = "EachUse/WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIs"
                 "HandedDown.*/ALoad",
        .reason = kMisalignedInHardware,
    },
    QboxFate{
        .tests = "EachUse/WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIs"
                 "HandedDown.*/AStore",
        .reason = kMisalignedInHardware,
    },
    QboxFate{
        .tests = "WhenAHandlerMakesTheStoreThatAHartRefusedAtAnOddAddress.*",
        .reason = kMisalignedInHardware,
    },
    QboxFate{
        .tests =
            "EachUse/WhenSupervisorModeUsesAWordAtAnOddAddress.*/AnAtomicSum",
        .reason = kMisalignedAtomic,
    },
    QboxFate{
        .tests = "EachUse/WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIs"
                 "HandedDown.*/AnAtomicSum",
        .reason = kMisalignedAtomic,
    },
    QboxFate{
        .tests =
            "EachWay/WhenSupervisorModeUsesAPageInAWayItsEntryDoesNotAllow."
            "*/ALoadFromAPageNotMarkedAccessed",
        .reason = kAccessedAndDirtyInHardware,
    },
    QboxFate{
        .tests =
            "EachWay/WhenSupervisorModeUsesAPageInAWayItsEntryDoesNotAllow."
            "*/AStoreToAPageNotMarkedDirty",
        .reason = kAccessedAndDirtyInHardware,
    },
    QboxFate{
        .tests = "WhenSupervisorModeStoresToAPageNotMarkedDirtyThatItHasJust"
                 "LoadedFrom.*",
        .reason = kAccessedAndDirtyInHardware,
    },
    QboxFate{
        .tests = "WhenSatpIsWrittenWithAnAddressSpaceIdentifier.*",
        .reason = kQemusPaging,
    },
    QboxFate{
        .tests =
            "EachKind/WhenSatpIsWrittenWithAKindOfPagingTheHartHasNot.*/Sv48",
        .reason = kQemusPaging,
    },
    QboxFate{
        .tests =
            "EachKind/WhenSatpIsWrittenWithAKindOfPagingTheHartHasNot.*/Sv57",
        .reason = kQemusPaging,
    },
    QboxFate{
        .tests = "EitherWay/WhenAStoreConditionalFollowsALoadReservedOfItsCell."
                 "*OverTheBus",
        .reason = kAtomicsSpin,
    },
    QboxFate{
        .tests = "EachReason/WhenAStoreConditionalFindsNoReservationOnItsCell."
                 "*OverTheBus",
        .reason = kAtomicsSpin,
    },
    QboxFate{
        .tests = "EachOperation/WhenAProgramUsesAnAtomicMemoryOperation."
                 "*OverTheBus",
        .reason = kAtomicsSpin,
    },
    QboxFate{
        .tests = "TheThreeOfEachMode/WhenACpuWithNoImsicWritesARegisterAnImsic"
                 "WouldAnswer.*/Miselect",
        .reason =
            "QEMU keeps miselect itself whenever it has the registers of "
            "the Advanced Interrupt Architecture, which a qbox_cpu always "
            "asks for",
    },
    QboxFate{
        .tests = "TheThreeOfEachMode/WhenACpuWithNoImsicWritesARegisterAnImsic"
                 "WouldAnswer.*/Siselect",
        .reason =
            "QEMU keeps siselect itself whenever it has the registers of "
            "the Advanced Interrupt Architecture, which a qbox_cpu always "
            "asks for",
    },
    QboxFate{
        .tests =
            "TheThree/WhenACpuWithAnImsicAndNoSupervisorModeWritesARegister"
            "OfThatModes.*",
        .reason = "QBox's CPU always has supervisor mode",
    },
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
