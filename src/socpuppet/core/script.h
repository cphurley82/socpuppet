#ifndef SOCPUPPET_CORE_SCRIPT_H_
#define SOCPUPPET_CORE_SCRIPT_H_

#include <coroutine>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <utility>
#include <variant>
#include <vector>

#include "socpuppet/core/time.h"

namespace socpuppet {

// The operations a script can ask its bus master to carry out. A script
// makes one where it is needed: `co_await Write32(0x10, 0xC0FFEE)`. They
// have the names the Python API uses (`sp.write32`), in C++'s spelling.
struct Read32 {
  std::uint64_t address;
};
struct Write32 {
  std::uint64_t address;
  std::uint32_t value;
};
// The same for a run of bytes of any length, in one access: a block of
// data, or a structure that does not fit in 32 bits.
struct Read {
  std::uint64_t address;
  std::size_t length;
};
struct Write {
  std::uint64_t address;
  std::vector<std::uint8_t> data;
};
// Read, and fail the simulation if the value is not the one expected.
struct Expect32 {
  std::uint64_t address;
  std::uint32_t value;
};
// Let simulated time pass.
struct Wait {
  Picoseconds duration;
};
// Wait until the interrupt line is high.
struct WaitIrq {};

using Op = std::variant<Read32, Write32, Read, Write, Expect32, Wait, WaitIrq>;

// What carrying an op out gives back to the script: nothing for most, a
// 32-bit value for a Read32, bytes for a Read.
using Result =
    std::variant<std::monostate, std::uint32_t, std::vector<std::uint8_t>>;

// A script for a bus master, written as a C++20 coroutine:
//
//   Script Boot() {
//     co_await Write32(0x10, 0xC0FFEE);
//     std::uint32_t value = co_await Read32(0x10);
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
    // What the op before gave back, for its co_await to return.
    Result result;

    Script get_return_object() {
      return Script{std::coroutine_handle<promise_type>::from_promise(*this)};
    }
    std::suspend_always initial_suspend() noexcept { return {}; }
    std::suspend_always final_suspend() noexcept { return {}; }
    void return_void() {}
    void unhandled_exception() { std::terminate(); }

    // co_await <op>: remember the op and suspend. A read resumes with what
    // the driver gave back, and the other ops resume with nothing. A read
    // whose driver gave nothing back resumes with zero, or with no bytes.
    struct Suspend {
      bool await_ready() const noexcept { return false; }
      void await_suspend(std::coroutine_handle<>) const noexcept {}
    };
    struct AwaitValue : Suspend {
      promise_type& promise;
      std::uint32_t await_resume() const noexcept {
        const auto* value = std::get_if<std::uint32_t>(&promise.result);
        return value == nullptr ? 0 : *value;
      }
    };
    struct AwaitBytes : Suspend {
      promise_type& promise;
      std::vector<std::uint8_t> await_resume() const noexcept {
        auto* bytes = std::get_if<std::vector<std::uint8_t>>(&promise.result);
        return bytes == nullptr ? std::vector<std::uint8_t>{}
                                : std::move(*bytes);
      }
    };
    struct AwaitNothing : Suspend {
      void await_resume() const noexcept {}
    };
    // An op whose kind is only known at run time resumes with whatever it
    // gave back.
    struct AwaitResult : Suspend {
      promise_type& promise;
      Result await_resume() const noexcept { return std::move(promise.result); }
    };
    AwaitResult await_transform(Op op) {
      pending = std::move(op);
      return AwaitResult{{}, *this};
    }
    AwaitValue await_transform(Read32 op) {
      pending = op;
      return AwaitValue{{}, *this};
    }
    AwaitBytes await_transform(Read op) {
      pending = op;
      return AwaitBytes{{}, *this};
    }
    AwaitNothing await_transform(Write op) { return HandOver(std::move(op)); }
    AwaitNothing await_transform(Write32 op) { return HandOver(op); }
    AwaitNothing await_transform(Expect32 op) { return HandOver(op); }
    AwaitNothing await_transform(Wait op) { return HandOver(op); }
    AwaitNothing await_transform(WaitIrq op) { return HandOver(op); }

   private:
    AwaitNothing HandOver(Op op) {
      pending = std::move(op);
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
  const Op* Next() {
    coroutine_.resume();
    // The op before has been given its result by now. Unless the driver
    // gives one back for the new op, it gets nothing.
    coroutine_.promise().result = {};
    return coroutine_.done() ? nullptr : &coroutine_.promise().pending;
  }

  // The result of the op just carried out, for the script's co_await to
  // return.
  void GiveBack(Result result) {
    coroutine_.promise().result = std::move(result);
  }

 private:
  explicit Script(std::coroutine_handle<promise_type> coroutine)
      : coroutine_(coroutine) {}

  std::coroutine_handle<promise_type> coroutine_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_SCRIPT_H_
