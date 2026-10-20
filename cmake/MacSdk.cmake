# Included before project(), as CMake picks the SDK there.
#
# Apple's clang, when no SDK is named, finds one by itself but then also
# searches /usr/local/include, ahead of every -isystem directory. That is
# where Homebrew keeps its headers on an Intel Mac, so its fmt would stand
# in for the one a dependency carries. Since CMake 4 no SDK is named unless
# asked for, so ask for the one the compiler would use anyway: named, the
# SDK is the only system directory clang searches. Apple silicon never
# meets this only because its Homebrew lives in /opt/homebrew. A build
# given its own SDK keeps it.
if(CMAKE_HOST_APPLE AND NOT CMAKE_OSX_SYSROOT)
  set(CMAKE_OSX_SYSROOT macosx)
endif()
