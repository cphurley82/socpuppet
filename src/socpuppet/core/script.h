#ifndef SOCPUPPET_CORE_SCRIPT_H_
#define SOCPUPPET_CORE_SCRIPT_H_

#include <coroutine>
#include <cstdint>
#include <exception>
#include <utility>
#include <variant>

#include "socpuppet/core/time.h"

namespace socpuppet {

// The operations a script can ask its bus master to carry out.
struct Read32 {
  std::uint64_t address;
};
struct Write32 {
  std::uint64_t address;
  std::uint32_t value;
};
// Read, and fail the simulation if the value is not the one expected.
struct Expect32 {
  std::uint64_t address;
  std::uint32_t value;
};
struct Wait {
  Picoseconds duration;
};
// Wait until the interrupt line is high.
struct WaitIrq {};

using Op = std::variant<Read32, Write32, Expect32, Wait, WaitIrq>;

// A script for a bus master, written as a C++20 coroutine:
//
//   Script boot() {
//     co_await write32(0x10, 0xC0FFEE);
//     std::uint32_t value = co_await read32(0x10);
//   }
//
// Each co_await hands one Op to whoever is driving the script and suspends.
// The driver carries the op out, gives a result back if there is one, and
// asks for the next op. It is the same shape as a Python generator: `yield`
// an op, get the result sent back.
//
// Coroutine arguments must be taken by value. A reference would dangle,
// because the coroutine outlives the call that created it.
class Script {
 public:
  struct promise_type {
    Op pending;
    std::uint32_t result = 0;

    Script get_return_object() {
      return Script{std::coroutine_handle<promise_type>::from_promise(*this)};
    }
    std::suspend_always initial_suspend() noexcept { return {}; }
    std::suspend_always final_suspend() noexcept { return {}; }
    void return_void() {}
    void unhandled_exception() { std::terminate(); }

    // co_await <op>: remember the op and suspend. A read resumes with the
    // value the driver gave back; the other ops resume with nothing.
    struct Suspend {
      bool await_ready() const noexcept { return false; }
      void await_suspend(std::coroutine_handle<>) const noexcept {}
    };
    struct AwaitValue : Suspend {
      promise_type& promise;
      std::uint32_t await_resume() const noexcept { return promise.result; }
    };
    struct AwaitNothing : Suspend {
      void await_resume() const noexcept {}
    };
    AwaitValue await_transform(Read32 op) {
      pending = op;
      return AwaitValue{{}, *this};
    }
    // An op whose kind is only known at run time. Resumes with the value
    // given back, which means something only if the op was a read.
    AwaitValue await_transform(Op op) {
      pending = op;
      return AwaitValue{{}, *this};
    }
    AwaitNothing await_transform(Write32 op) { return hand_over(op); }
    AwaitNothing await_transform(Expect32 op) { return hand_over(op); }
    AwaitNothing await_transform(Wait op) { return hand_over(op); }
    AwaitNothing await_transform(WaitIrq op) { return hand_over(op); }

   private:
    AwaitNothing hand_over(Op op) {
      pending = op;
      return {};
    }
  };

  Script(Script&& other) noexcept
      : coroutine_(std::exchange(other.coroutine_, nullptr)) {}
  ~Script() {
    if (coroutine_) coroutine_.destroy();
  }

  // Runs the script up to its next op and returns it, or nullptr when the
  // script has finished.
  const Op* next() {
    coroutine_.resume();
    return coroutine_.done() ? nullptr : &coroutine_.promise().pending;
  }

  // The result of the op just carried out, for the script's co_await to return.
  void give_back(std::uint32_t result) { coroutine_.promise().result = result; }

 private:
  explicit Script(std::coroutine_handle<promise_type> coroutine)
      : coroutine_(coroutine) {}

  std::coroutine_handle<promise_type> coroutine_;
};

inline Read32 read32(std::uint64_t address) { return {address}; }
inline Write32 write32(std::uint64_t address, std::uint32_t value) {
  return {.address = address, .value = value};
}
inline Expect32 expect32(std::uint64_t address, std::uint32_t value) {
  return {.address = address, .value = value};
}
// Python calls this one `wait`; here that name belongs to sc_module::wait.
inline Wait wait_for(Picoseconds duration) { return {duration}; }
inline WaitIrq wait_irq() { return {}; }

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_SCRIPT_H_
