#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <functional>
#include <list>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <systemc>
#include <tlm>

#include "socpuppet/bindings/python_executor.h"
#include "socpuppet/bindings/python_script.h"
#include "socpuppet/core/elf_image.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/far_end.h"
#include "socpuppet/models/ideal_nand.h"
#include "socpuppet/models/pciem_host.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/models/virtio_9p.h"
#include "socpuppet/models/virtio_blk.h"
#include "socpuppet/models/virtio_fs.h"
#include "socpuppet/models/virtio_net.h"
#include "socpuppet/platform/errors.h"
#include "socpuppet/platform/logging.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/time_conversion.h"

namespace py = pybind11;

namespace {

// The SystemC kernel is a process-wide singleton that cannot be restarted,
// so the first Platform built in a process is the only one it can have.
//
// That holds for a build that fails part-way too. The modules it had
// created are destroyed, but the kernel keeps their processes, and would
// run them on modules that are gone.
class KernelClaim {
 public:
  KernelClaim() {
    switch (State()) {
      case Kernel::kFree:
        break;
      case Kernel::kBuilding:
        throw std::runtime_error(
            "An earlier build() failed part-way, and what it had created "
            "cannot be taken out of the SystemC kernel again. So this "
            "process cannot build a Platform any more: fix the description "
            "and run it in a new process.");
      case Kernel::kBuilt:
        throw std::runtime_error(
            "A process can build only one Platform, because the SystemC "
            "kernel underneath it cannot be restarted. Build each Platform "
            "in its own process. In pytest, mark the test with "
            "@pytest.mark.platform, which does that for you (enable it with "
            "pytest_plugins = [\"socpuppet.pytest_plugin\"] in "
            "conftest.py).");
    }
    State() = Kernel::kBuilding;
  }

  // The platform this claim was taken for is complete.
  void Built() { State() = Kernel::kBuilt; }

 private:
  enum class Kernel { kFree, kBuilding, kBuilt };
  static Kernel& State() {
    static Kernel state = Kernel::kFree;
    return state;
  }
};

// What Python's Platform.build() drives: the C++ platform, plus the claim
// on this process's one kernel.
struct NativePlatform {
  explicit NativePlatform(bool color_log) { socpuppet::InitLogging(color_log); }

  // Runs part of the simulation with the GIL released, so that Python
  // scripts (and other Python threads) can run while the kernel does.
  template <typename Simulate>
  void WithoutGil(Simulate simulate) {
    py::gil_scoped_release release;
    simulate();
  }

  // `answer`, a Python callable from bytes to bytes, as what a device that
  // hands its requests to an answerer calls. The device calls it from its
  // own thread process, so it runs through the executor, on Python's
  // stack.
  std::function<std::vector<std::uint8_t>(std::span<const std::uint8_t>)>
  Answerer(py::object answer) {
    py::object& kept = python_answerers.emplace_back(std::move(answer));
    return [this, &kept](std::span<const std::uint8_t> request) {
      std::vector<std::uint8_t> answered;
      python_executor.Run([&] {
        const py::bytes got = kept(py::bytes(
            reinterpret_cast<const char*>(request.data()), request.size()));
        const std::string_view bytes{got};
        answered.assign(bytes.begin(), bytes.end());
      });
      return answered;
    };
  }

  KernelClaim kernel_claim;  // first member: checked before any module is built
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  socpuppet::PythonExecutor python_executor{"socpuppet_python_executor"};
  // Declared last, so the Python scripts and answerers are dropped first,
  // while the GIL is held by whoever is destroying this platform from
  // Python.
  std::list<socpuppet::PythonScript> python_scripts;
  std::list<py::object> python_answerers;
};

}  // namespace

PYBIND11_MODULE(_core, m) {
  // C++ failures that have a Python exception of their own. pybind11 fixes
  // the signature of a translator: it takes the exception_ptr by value.
  // NOLINTNEXTLINE(performance-unnecessary-value-param)
  py::register_exception_translator([](std::exception_ptr failure) {
    try {
      if (failure) std::rethrow_exception(failure);
    } catch (const socpuppet::ExpectationFailed& expectation) {
      py::object type =
          py::module_::import("socpuppet.errors").attr("ExpectationFailed");
      PyErr_SetString(type.ptr(), expectation.what());
    } catch (const socpuppet::BusError& refusal) {
      py::object type =
          py::module_::import("socpuppet.errors").attr("BusError");
      PyErr_SetString(type.ptr(), refusal.what());
    }
  });

  // An ELF image as (word size in bits, entry point, segments), where each
  // segment is (physical address, bytes).
  m.def("read_elf", [](const std::string& path) {
    const socpuppet::ElfImage image = socpuppet::ReadElfImage(path);
    py::list segments;
    for (const socpuppet::ElfImage::Segment& each : image.segments) {
      segments.append(py::make_tuple(
          each.address,
          py::bytes(reinterpret_cast<const char*>(each.bytes.data()),
                    each.bytes.size())));
    }
    return py::make_tuple(image.xlen, image.entry, segments);
  });

  // The quantum SystemC is running with, which is one for the whole
  // process. For checking that a described quantum arrived.
  m.def("global_quantum_in_picoseconds", [] {
    return socpuppet::ToPicoseconds(tlm::tlm_global_quantum::instance().get())
        .count();
  });

  // implementations() and Platform.ports() exist so the Python catalogue can
  // be checked against the registry (tests/python/test_catalogue.py).
  m.def("implementations",
        [] { return socpuppet::BuiltinComponents().Implementations(); });
  // Whether this build has QBox's CPU. Every build has the name
  // "qbox_cpu", and one without QBox refuses it.
  m.attr("has_qbox") = SOCPUPPET_HAS_QBOX != 0;
  // Whether this build has pciem, for a real host. Every build has the
  // name "pciem_host", and one without pciem refuses it.
  m.attr("has_pciem") = SOCPUPPET_HAS_PCIEM != 0;

  py::class_<NativePlatform>(m, "Platform")
      .def(py::init<bool>(), py::arg("color_log"))
      .def("add",
           [](NativePlatform& self, const std::string& path,
              const std::string& implementation,
              const socpuppet::Config& config) {
             self.platform.Add(path, implementation, config);
           })
      .def("bind",
           [](NativePlatform& self, const std::string& source,
              const std::string& sink,
              bool traced) { self.platform.Bind(source, sink, traced); })
      // Each record is (time in ps, source, sink, is_write, address, data, ok).
      .def("trace_records",
           [](NativePlatform& self) {
             py::list records;
             for (const socpuppet::TraceRecord& each :
                  self.platform.RecordedTrace().Records()) {
               records.append(py::make_tuple(
                   each.time.count(), each.source, each.sink, each.is_write,
                   each.address,
                   py::bytes(reinterpret_cast<const char*>(each.data.data()),
                             each.data.size()),
                   each.ok));
             }
             return records;
           })
      .def("set_script",
           [](NativePlatform& self, const std::string& path,
              py::object generator_function) {
             socpuppet::PythonScript& script = self.python_scripts.emplace_back(
                 std::move(generator_function), self.python_executor);
             self.platform.ModuleAt<socpuppet::ScriptedBusMaster>(path)
                 .SetScript([&script] { return script.Play(); });
           })
      // What the serial transport at `path` (a UART, a virtio console) has
      // transmitted after its first `since` bytes, and nothing if it has
      // not sent that many. As bytes, because firmware may send anything.
      // Only that tail is copied, so a reader that keeps up pays for what
      // is new, not for everything sent so far.
      .def(
          "far_end_output",
          [](NativePlatform& self, const std::string& path, std::size_t since) {
            const std::string_view output{
                self.platform.ModuleAt<socpuppet::FarEnd>(path).Output()};
            return py::bytes(output.substr(std::min(since, output.size())));
          })
      // Hands the serial transport at `path` bytes to receive, as if they
      // had come in on its line.
      .def("far_end_write",
           [](NativePlatform& self, const std::string& path,
              const py::bytes& received) {
             self.platform.ModuleAt<socpuppet::FarEnd>(path).Write(
                 std::string_view{received});
           })
      // Puts a disk image on the virtio disk at `path`, from its first
      // sector on. Too large an image is refused (ValueError).
      .def("disk_load",
           [](NativePlatform& self, const std::string& path,
              const py::bytes& image) {
             const std::string_view bytes{image};
             self.platform.ModuleAt<socpuppet::VirtioBlk>(path).Load(
                 std::span(reinterpret_cast<const std::uint8_t*>(bytes.data()),
                           bytes.size()));
           })
      // Everything on the virtio disk at `path`.
      .def("disk_contents",
           [](NativePlatform& self, const std::string& path) {
             const std::vector<std::uint8_t> bytes =
                 self.platform.ModuleAt<socpuppet::VirtioBlk>(path).Contents();
             return py::bytes(reinterpret_cast<const char*>(bytes.data()),
                              bytes.size());
           })
      // The pciem host at `path`: put its function on this machine's bus,
      // the descriptor it says the host has made writes on, take those
      // writes, and refresh what the host reads.
      .def("pciem_host_start",
           [](NativePlatform& self, const std::string& path) {
             self.platform.ModuleAt<socpuppet::PciemHost>(path).Start();
           })
      .def(
          "pciem_host_event_fd",
          [](NativePlatform& self, const std::string& path) {
            return self.platform.ModuleAt<socpuppet::PciemHost>(path).EventFd();
          })
      .def("pciem_host_service",
           [](NativePlatform& self, const std::string& path) {
             self.platform.ModuleAt<socpuppet::PciemHost>(path).Service();
           })
      .def("pciem_host_refresh",
           [](NativePlatform& self, const std::string& path) {
             self.platform.ModuleAt<socpuppet::PciemHost>(path).Refresh();
           })
      // Programs an image into the NAND chip at `path`, from its first page
      // on. Too long an image is refused (ValueError).
      .def("nand_load",
           [](NativePlatform& self, const std::string& path,
              const py::bytes& image) {
             const std::string_view bytes{image};
             self.platform.ModuleAt<socpuppet::IdealNand>(path).Load(
                 std::span(reinterpret_cast<const std::uint8_t*>(bytes.data()),
                           bytes.size()));
           })
      // Every page of the NAND chip at `path`, in order.
      .def("nand_contents",
           [](NativePlatform& self, const std::string& path) {
             const std::vector<std::uint8_t> bytes =
                 self.platform.ModuleAt<socpuppet::IdealNand>(path).Contents();
             return py::bytes(reinterpret_cast<const char*>(bytes.data()),
                              bytes.size());
           })
      // Hands the virtio network device at `path` a frame, as if it had
      // come in on its wire.
      .def("net_send",
           [](NativePlatform& self, const std::string& path,
              const py::bytes& frame) {
             const std::string_view bytes{frame};
             self.platform.ModuleAt<socpuppet::VirtioNet>(path).Send(
                 {bytes.begin(), bytes.end()});
           })
      // Every frame the driver of the network device at `path` has sent.
      .def("net_received",
           [](NativePlatform& self, const std::string& path) {
             py::list frames;
             for (const auto& frame :
                  self.platform.ModuleAt<socpuppet::VirtioNet>(path)
                      .Received()) {
               frames.append(py::bytes(
                   reinterpret_cast<const char*>(frame.data()), frame.size()));
             }
             return frames;
           })
      // How many frames the network device at `path` dropped for want of
      // room.
      .def(
          "net_dropped",
          [](NativePlatform& self, const std::string& path) {
            return self.platform.ModuleAt<socpuppet::VirtioNet>(path).Dropped();
          })
      // Names the share of the virtio file system device at `path` `tag`,
      // and has `answer`, a Python callable from a FUSE request's bytes to
      // its answer's, serve it.
      .def("virtio_fs_serve",
           [](NativePlatform& self, const std::string& path,
              const std::string& tag, py::object answer) {
             auto& fs = self.platform.ModuleAt<socpuppet::VirtioFs>(path);
             fs.SetTag(tag);
             fs.SetAnswerer(self.Answerer(std::move(answer)));
           })
      // Names the share of the virtio 9P transport at `path` `tag`, and has
      // `answer`, a Python callable from a T-message's bytes to its
      // R-message's, serve it.
      .def("virtio_9p_serve",
           [](NativePlatform& self, const std::string& path,
              const std::string& tag, py::object answer) {
             auto& ninep = self.platform.ModuleAt<socpuppet::Virtio9p>(path);
             ninep.SetTag(tag);
             ninep.SetAnswerer(self.Answerer(std::move(answer)));
           })
      // Each port is (name, "bus" or "wire", "source" or "sink", required).
      .def("ports",
           [](NativePlatform& self, const std::string& path) {
             py::list ports;
             for (const socpuppet::Port& each : self.platform.Ports(path)) {
               const bool is_source =
                   RoleOf(each) == socpuppet::Port::Role::kSource;
               ports.append(py::make_tuple(each.name, ToString(KindOf(each)),
                                           is_source ? "source" : "sink",
                                           each.required));
             }
             return ports;
           })
      .def("elaborate",
           [](NativePlatform& self) {
             self.platform.Elaborate();
             self.kernel_claim.Built();
           })
      .def("run",
           [](NativePlatform& self) {
             self.WithoutGil([&] { self.platform.Run(); });
           })
      .def("set_quantum",
           [](NativePlatform& self, std::uint64_t picoseconds) {
             self.platform.SetQuantum(
                 socpuppet::ToScTime(socpuppet::Picoseconds{picoseconds}));
           })
      .def("run_for",
           [](NativePlatform& self, std::uint64_t picoseconds) {
             self.WithoutGil([&] {
               self.platform.Run(
                   socpuppet::ToScTime(socpuppet::Picoseconds{picoseconds}));
             });
           })
      .def("step",
           [](NativePlatform& self) {
             bool stepped = false;
             self.WithoutGil([&] { stepped = self.platform.Step(); });
             return stepped;
           })
      // None when nothing is scheduled.
      .def("picoseconds_to_next_activity",
           [](NativePlatform& self) -> std::optional<std::uint64_t> {
             std::optional<sc_core::sc_time> ahead;
             self.WithoutGil(
                 [&] { ahead = self.platform.TimeToNextActivity(); });
             if (!ahead) return std::nullopt;
             return socpuppet::ToPicoseconds(*ahead).count();
           })
      .def("time_in_picoseconds",
           [](NativePlatform& self) {
             return socpuppet::ToPicoseconds(self.platform.Time()).count();
           })
      // debug_read returns None, and debug_write False, when nothing took the
      // access.
      .def("debug_read",
           [](NativePlatform& self, const std::string& via,
              std::uint64_t address, std::size_t length) -> py::object {
             std::string data(length, '\0');
             if (!self.platform.DebugRead(
                     via, address, std::as_writable_bytes(std::span{data}))) {
               return py::none();
             }
             return py::bytes(data);
           })
      .def("debug_write", [](NativePlatform& self, const std::string& via,
                             std::uint64_t address, const std::string& data) {
        return self.platform.DebugWrite(via, address,
                                        std::as_bytes(std::span{data}));
      });
}
