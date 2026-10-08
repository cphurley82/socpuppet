#ifndef TESTS_CPP_SUPPORT_TEST_COMPONENTS_H_
#define TESTS_CPP_SUPPORT_TEST_COMPONENTS_H_

#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <systemc>

#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/interrupt_source.h"
#include "tests/cpp/support/line_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/recording_target.h"

// A test's own components, put into a registry so that a platform can be
// composed with them by name, as it is with the real ones. Each is added
// under the implementation name the test gives, and is made with what the
// test hands over here. The port names are the members' own.

// A bus driver that runs `body`. Port: "socket".
inline void AddBusDriver(socpuppet::Registry& registry,
                         std::string implementation,
                         std::function<void(BusDriver&)> body) {
  registry.Add(
      std::move(implementation),
      [body = std::move(body)](const char* name, socpuppet::Parameters&) {
        auto module = std::make_unique<BusDriver>(name, body);
        std::vector<socpuppet::Port> ports{
            socpuppet::InitiatorPort("socket", module->socket)};
        return socpuppet::Instance{.module = std::move(module),
                                   .ports = std::move(ports)};
      });
}

// A line driver that runs `body`. Port: "line".
inline void AddLineDriver(socpuppet::Registry& registry,
                          std::string implementation, Drive body) {
  registry.Add(
      std::move(implementation),
      [body = std::move(body)](const char* name, socpuppet::Parameters&) {
        auto module = std::make_unique<LineDriver>(name, body);
        std::vector<socpuppet::Port> ports{
            socpuppet::WireSourcePort("line", module->line)};
        return socpuppet::Instance{.module = std::move(module),
                                   .ports = std::move(ports)};
      });
}

// A line watcher. Port: "line".
inline void AddLineWatcher(socpuppet::Registry& registry,
                           std::string implementation) {
  registry.Add(std::move(implementation),
               [](const char* name, socpuppet::Parameters&) {
                 auto module = std::make_unique<LineWatcher>(name);
                 std::vector<socpuppet::Port> ports{
                     socpuppet::WireSinkPort("line", module->line)};
                 return socpuppet::Instance{.module = std::move(module),
                                            .ports = std::move(ports)};
               });
}

// A device with an interrupt line, which runs `body`. Ports: "socket" and
// "line".
inline void AddInterruptSource(socpuppet::Registry& registry,
                               std::string implementation,
                               std::function<void(InterruptSource&)> body) {
  registry.Add(
      std::move(implementation),
      [body = std::move(body)](const char* name, socpuppet::Parameters&) {
        auto module = std::make_unique<InterruptSource>(name, body);
        std::vector<socpuppet::Port> ports{
            socpuppet::TargetPort("socket", module->socket),
            socpuppet::WireSourcePort("line", module->line)};
        return socpuppet::Instance{.module = std::move(module),
                                   .ports = std::move(ports)};
      });
}

// A target that records each access in `accesses`, which has to outlive
// the platform, and takes `latency` to answer. Port: "socket".
inline void AddRecordingTarget(
    socpuppet::Registry& registry, std::string implementation,
    std::vector<RecordedAccess>& accesses,
    const sc_core::sc_time& latency = sc_core::SC_ZERO_TIME) {
  registry.Add(std::move(implementation),
               [&accesses, latency](const char* name, socpuppet::Parameters&) {
                 auto module =
                     std::make_unique<RecordingTarget>(name, accesses, latency);
                 std::vector<socpuppet::Port> ports{
                     socpuppet::TargetPort("socket", module->socket)};
                 return socpuppet::Instance{.module = std::move(module),
                                            .ports = std::move(ports)};
               });
}

#endif  // TESTS_CPP_SUPPORT_TEST_COMPONENTS_H_
