#ifndef SOCPUPPET_PLATFORM_LOGGING_H_
#define SOCPUPPET_PLATFORM_LOGGING_H_

#include <scc/report.h>

namespace socpuppet {

// Sets up the one log for the whole process: SystemC reports, SCC's models
// and our own all go through SCC's handler. Written synchronously, so there
// is no background thread and lines appear in the order they happen.
//
// `color` suits a terminal and is wrong for a file or a pipe.
inline void init_logging(bool color) {
  scc::init_logging(scc::LogConfig()
                        .logLevel(scc::log::WARNING)
                        .coloredOutput(color)
                        .logAsync(false));
}

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_LOGGING_H_
