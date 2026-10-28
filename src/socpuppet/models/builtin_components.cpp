#include "socpuppet/models/builtin_components.h"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <scc/router.h>

#include "socpuppet/core/time.h"
#include "socpuppet/models/aplic.h"
#include "socpuppet/models/behavioral_nvme.h"
#include "socpuppet/models/d2d_link.h"
#include "socpuppet/models/dbt_rise_cpu.h"
#include "socpuppet/models/dma_engine.h"
#include "socpuppet/models/flash_controller.h"
#include "socpuppet/models/ideal_nand.h"
#include "socpuppet/models/imsic.h"
#include "socpuppet/models/iommu.h"
#include "socpuppet/models/machine_timer.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/models/msi_receiver.h"
#include "socpuppet/models/ns16550.h"
#include "socpuppet/models/nvme_frontend.h"
#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/models/pcie_endpoint.h"
#include "socpuppet/models/pcie_root_complex.h"
#if SOCPUPPET_HAS_PCIEM
#include "socpuppet/core/pciem_device.h"
#include "socpuppet/models/pciem_host.h"
#endif
#include "socpuppet/models/plic.h"
#if SOCPUPPET_HAS_QBOX
#include "socpuppet/models/qbox_cpu.h"
#endif
#include "socpuppet/models/rom.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/models/spi_flash.h"
#include "socpuppet/models/system_controller.h"
#include "socpuppet/models/virtio_9p.h"
#include "socpuppet/models/virtio_blk.h"
#include "socpuppet/models/virtio_console.h"
#include "socpuppet/models/virtio_fs.h"
#include "socpuppet/models/virtio_net.h"
#include "socpuppet/models/virtio_rng.h"
#include "socpuppet/models/watchdog.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/slots.h"

namespace socpuppet {

static_assert(AplicSlot<Aplic>);
static_assert(IommuSlot<Iommu>);
static_assert(MemorySlot<Memory>);
static_assert(MemorySlot<Rom>);
static_assert(VirtioDeviceSlot<Virtio9p>);
static_assert(VirtioDeviceSlot<VirtioBlk>);
static_assert(VirtioDeviceSlot<VirtioConsole>);
static_assert(VirtioDeviceSlot<VirtioFs>);
static_assert(VirtioDeviceSlot<VirtioNet>);
static_assert(VirtioDeviceSlot<VirtioRng>);
static_assert(WatchdogSlot<Watchdog>);
static_assert(LinkEndpointSlot<PassThroughLinkEndpoint>);
static_assert(LinkEndpointSlot<D2dLinkEndpoint>);
static_assert(UartSlot<Ns16550>);
static_assert(MachineTimerSlot<MachineTimer>);
static_assert(InterruptControllerSlot<Plic>);
static_assert(NvmeFunctionSlot<BehavioralNvme>);
static_assert(NandSlot<IdealNand>);
static_assert(CpuSlot<ScriptedBusMaster>);
static_assert(CpuSlot<DbtRiseCpu>);
#if SOCPUPPET_HAS_QBOX
static_assert(CpuSlot<QboxCpu>);
#endif

namespace {

// The ports of a RISC-V hart here: the bus, `time` from a machine timer,
// `csr` to an IMSIC, and the interrupt and reset inputs. Both CPUs have
// them.
template <typename Hart>
std::vector<Port> HartPorts(Hart& hart) {
  return {InitiatorPort("socket", hart.socket),
          InitiatorPort("time", hart.time, /*required=*/false),
          InitiatorPort("csr", hart.csr, /*required=*/false),
          WireSinkPort("irq", hart.irq),
          WireSinkPort("timer_irq", hart.timer_irq),
          WireSinkPort("supervisor_irq", hart.supervisor_irq),
          WireSinkPort("reset", hart.reset)};
}

// The highest interrupt identity an IMSIC's files may have. The AIA
// specification starts at 63 and stops at 2047.
constexpr Within kInterruptIdentities{.least = 63, .most = 2047};

// A number that cannot be zero, for a rate that is divided by: a link
// carrying no bytes in a nanosecond would never carry anything. A time of
// zero means something, so no latency or training time has a range.
constexpr Within kAtLeastOne{.least = 1};

// A MAC address, as a 48-bit number with its first byte highest.
constexpr Within kMacAddresses{.most = (std::uint64_t{1} << 48) - 1};

// The address a virtio network device has unless it is given one,
// 02:00:5e:00:53:01: locally administered (the second-lowest bit of the
// first byte is set), so it is no manufacturer's. Python's VirtioNet has
// the same default.
constexpr std::uint64_t kVirtioNetMac = 0x0200'5E00'5301;

// How many 512-byte sectors a virtio disk may have: at least one, and no
// more than the bytes of them can be counted in 64 bits.
constexpr Within kDiskSectors{
    .least = 1, .most = std::numeric_limits<std::uint64_t>::max() / 512};

// What a NAND chip's geometry is made of: counts that a controller reads
// from 32-bit registers, and none of which can be nothing.
constexpr Within kNandCount{.least = 1, .most = 0xFFFF'FFFF};
// A flash holds a byte at the least, and at the most what three address
// bytes reach: 16 MiB. That its size is a power of two, as the chip needs,
// is the Python component's to check: a range cannot say it.
constexpr Within kFlashSize{.least = 1, .most = 0x100'0000};

}  // namespace

Registry BuiltinComponents() {
  Registry registry;
  registry.Add("aplic", [](const char* name, Parameters& parameters) {
    auto module =
        std::make_unique<Aplic>(name, parameters.Optional("messages_to", 0));
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            InitiatorPort("msi", module->msi)};
    AddNumberedPorts(ports, "source", 1, module->sources, WireSinkPort);
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("behavioral_nvme", [](const char* name, Parameters& parameters) {
    const std::uint64_t vectors =
        parameters.Required("vectors", kInterruptVectors);
    auto module = std::make_unique<BehavioralNvme>(
        name, parameters.Required("blocks"), vectors);
    std::vector<Port> ports{TargetPort("bar0", module->bar0),
                            InitiatorPort("dma", module->dma)};
    // A host need not use every vector, so a line may be left unconnected.
    AddNumberedPorts(ports, "irq", 0, module->irq,
                     [](std::string port, sc_core::sc_out<bool>& line) {
                       return WireSourcePort(std::move(port), line,
                                             /*required=*/false);
                     });
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // How DBT-RISE runs the core is the build's to say, in
  // SOCPUPPET_DBT_RISE_DEFAULT_BACKEND (cmake/Dependencies.cmake). It is not
  // a parameter because a parameter here is a number, and a backend a name.
  registry.Add("dbt_rise_cpu", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<DbtRiseCpu>(
        name, parameters.Required("xlen"), parameters.Required("reset_vector"),
        static_cast<std::uint16_t>(
            parameters.Optional("gdb_port", 0, kFitsIn16Bits)),
        DbtRiseCpuExtras{
            .floating_point = parameters.Optional("floating_point", 0) != 0,
            .supervisor_mode = parameters.Optional("supervisor_mode", 0) != 0},
        /*backend=*/std::nullopt);
    std::vector<Port> ports = HartPorts(*module);
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // QBox's CPU is QEMU's, which is GPL, so it is built only by whoever
  // asks for it (tools/build_qbox.py). The name is here either way, so that
  // a build without it says how to get one.
#if SOCPUPPET_HAS_QBOX
  registry.Add("qbox_cpu", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<QboxCpu>(
        name, parameters.Required("xlen"), parameters.Required("reset_vector"),
        static_cast<std::uint16_t>(
            parameters.Optional("gdb_port", 0, kFitsIn16Bits)));
    std::vector<Port> ports = HartPorts(*module);
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
#else
  registry.Add("qbox_cpu", [](const char*, Parameters&) -> Instance {
    throw std::invalid_argument(
        "This build of socpuppet has no qbox_cpu. Build QBox with "
        "tools/build_qbox.py, then socpuppet with `cmake --preset qbox`, "
        "which sets SOCPUPPET_QBOX_DIR to where the tool installs it.");
  });
#endif
  // pciem is GPL-2.0-only, so a real host is built only by whoever asks
  // for it (tools/build_pciem.py). The name is here either way, so that a
  // build without it says how to get one.
#if SOCPUPPET_HAS_PCIEM
  AddPciemHost(registry, "pciem_host", OpenPciemDevice);
#else
  registry.Add("pciem_host", [](const char*, Parameters&) -> Instance {
    throw std::invalid_argument(
        "This build of socpuppet has no pciem_host. Build pciem's module "
        "with tools/build_pciem.py, then socpuppet with `cmake --preset "
        "pciem`, which sets SOCPUPPET_PCIEM_DIR to where the tool puts it.");
  });
#endif
  registry.Add("dma_engine", [](const char* name, Parameters&) {
    auto module = std::make_unique<DmaEngine>(name);
    std::vector<Port> ports{TargetPort("cpu", module->cpu),
                            InitiatorPort("host", module->host),
                            InitiatorPort("local", module->local),
                            // Firmware may poll the status and leave the
                            // line alone.
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("flash_controller", [](const char* name, Parameters&) {
    auto module = std::make_unique<FlashController>(name);
    std::vector<Port> ports{
        TargetPort("cpu", module->cpu), InitiatorPort("local", module->local),
        InitiatorPort("nand", module->nand),
        // Firmware may poll the status and leave the line alone.
        WireSourcePort("irq", module->irq,
                       /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("ideal_nand", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<IdealNand>(
        name,
        NandGeometry{.page_size = static_cast<std::uint32_t>(
                         parameters.Required("page_size", kNandCount)),
                     .pages_per_block = static_cast<std::uint32_t>(
                         parameters.Required("pages_per_block", kNandCount)),
                     .blocks = static_cast<std::uint32_t>(
                         parameters.Required("blocks", kNandCount))});
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("iommu", [](const char* name, Parameters&) {
    auto module = std::make_unique<Iommu>(name);
    std::vector<Port> ports{
        TargetPort("socket", module->socket),
        TargetPort("target", module->target),
        InitiatorPort("initiator", module->initiator),
        WireSourcePort("irq", module->irq, /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("imsic", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<Imsic>(
        name, static_cast<std::uint32_t>(
                  parameters.Required("identities", kInterruptIdentities)));
    // The supervisor's page and line are for a platform whose firmware
    // leaves machine mode, and one that never does has no use for them.
    // `csr` has to go to a hart: a file can only be switched on through
    // it, so with nothing there no message would ever interrupt.
    std::vector<Port> ports{
        TargetPort("machine", module->machine),
        TargetPort("supervisor", module->supervisor, /*required=*/false),
        TargetPort("csr", module->csr), WireSourcePort("irq", module->irq),
        WireSourcePort("supervisor_irq", module->supervisor_irq,
                       /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("machine_timer", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<MachineTimer>(
        name, parameters.Required("frequency_hz", {.least = 1}));
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            // A hart that never reads `time` has no use
                            // for it.
                            TargetPort("time", module->time,
                                       /*required=*/false),
                            WireSourcePort("irq", module->irq)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("memory", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<Memory>(name, parameters.Required("size"));
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("msi_receiver", [](const char* name, Parameters&) {
    auto module = std::make_unique<MsiReceiver>(name);
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            WireSourcePort("irq", module->irq)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("ns16550", [](const char* name, Parameters&) {
    auto module = std::make_unique<Ns16550>(name);
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            // A console that is polled leaves the line
                            // alone.
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("nvme_frontend", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<NvmeFrontend>(
        name, parameters.Required("vectors", kInterruptVectors));
    std::vector<Port> ports{TargetPort("bar0", module->bar0),
                            InitiatorPort("dma", module->dma),
                            TargetPort("cpu", module->cpu),
                            // Firmware may poll the status and leave the
                            // line alone.
                            WireSourcePort("cpu_irq", module->cpu_irq,
                                           /*required=*/false)};
    // A host need not use every vector, so a line may be left unconnected.
    AddNumberedPorts(ports, "irq", 0, module->irq,
                     [](std::string port, sc_core::sc_out<bool>& line) {
                       return WireSourcePort(std::move(port), line,
                                             /*required=*/false);
                     });
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // One end of a link. The die's side may be left unconnected in either
  // direction; the peer side must be bound to the other endpoint.
  registry.Add("pass_through_link_endpoint", [](const char* name, Parameters&) {
    auto module = std::make_unique<PassThroughLinkEndpoint>(name);
    std::vector<Port> ports{
        TargetPort("target", module->target, /*required=*/false),
        InitiatorPort("initiator", module->initiator, /*required=*/false),
        InitiatorPort("peer_initiator", module->peer_initiator),
        TargetPort("peer_target", module->peer_target)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // One end of the real link. Its mainband and sideband peer sides must
  // be bound to the other end; everything on its own die's side is
  // optional, because a die may only send, only receive, or leave the
  // link's registers unmapped.
  registry.Add(
      "d2d_link_endpoint", [](const char* name, Parameters& parameters) {
        auto module = std::make_unique<D2dLinkEndpoint>(
            name, Nanoseconds(parameters.Optional("latency_ns", 20)),
            parameters.Optional("bytes_per_ns", 16, kAtLeastOne),
            Nanoseconds(parameters.Optional("training_ns", 1'000'000)));
        std::vector<Port> ports{
            TargetPort("target", module->target, /*required=*/false),
            InitiatorPort("initiator", module->initiator, /*required=*/false),
            InitiatorPort("peer_initiator", module->peer_initiator),
            TargetPort("peer_target", module->peer_target),
            TargetPort("sideband", module->sideband, /*required=*/false),
            InitiatorPort("sideband_peer_initiator",
                          module->sideband_peer_initiator),
            TargetPort("sideband_peer_target", module->sideband_peer_target),
            WireSourcePort("reset", module->reset, /*required=*/false),
            WireSourcePort("irq", module->irq, /*required=*/false)};
        return Instance{.module = std::move(module), .ports = std::move(ports)};
      });
  registry.Add("pcie_endpoint", [](const char* name, Parameters& parameters) {
    const std::uint64_t vectors =
        parameters.Required("vectors", kInterruptVectors);
    auto module = std::make_unique<PcieEndpoint>(
        name,
        PcieEndpointRegisters::Identity{
            .vendor_id = static_cast<std::uint16_t>(
                parameters.Required("vendor_id", kFitsIn16Bits)),
            .device_id = static_cast<std::uint16_t>(
                parameters.Required("device_id", kFitsIn16Bits)),
            .class_code = static_cast<std::uint32_t>(
                parameters.Required("class_code", kFitsIn24Bits))},
        parameters.Required("function_size"), vectors);
    std::vector<Port> ports{TargetPort("from_host", module->from_host),
                            InitiatorPort("to_host", module->to_host),
                            InitiatorPort("bar0", module->bar0),
                            TargetPort("dma", module->dma)};
    AddNumberedPorts(ports, "irq", 0, module->irq, WireSinkPort);
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add(
      "pcie_root_complex", [](const char* name, Parameters& parameters) {
        auto module = std::make_unique<PcieRootComplex>(
            name, parameters.Required("mmio_base"));
        std::vector<Port> ports{TargetPort("ecam", module->ecam),
                                TargetPort("mmio", module->mmio),
                                InitiatorPort("dma", module->dma),
                                InitiatorPort("to_device", module->to_device),
                                TargetPort("from_device", module->from_device)};
        return Instance{.module = std::move(module), .ports = std::move(ports)};
      });
  // Its sources are ports "source1" to "source31", numbered as the PLIC
  // numbers them.
  registry.Add("plic", [](const char* name, Parameters&) {
    auto module = std::make_unique<Plic>(name);
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            WireSourcePort("irq", module->irq)};
    AddNumberedPorts(ports, "source", 1, module->sources, WireSinkPort);
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("rom", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<Rom>(name, parameters.Required("size"));
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("scripted_bus_master", [](const char* name, Parameters&) {
    auto module = std::make_unique<ScriptedBusMaster>(name);
    std::vector<Port> ports{InitiatorPort("socket", module->socket),
                            WireSinkPort("irq", module->irq),
                            WireSinkPort("timer_irq", module->timer_irq),
                            WireSinkPort("reset", module->reset)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add(
      "system_controller", [](const char* name, Parameters& parameters) {
        auto module = std::make_unique<SystemController>(
            name,
            static_cast<std::uint32_t>(
                parameters.Optional("die", 0, kFitsIn32Bits)),
            static_cast<std::uint32_t>(
                parameters.Optional("boot_address", 0, kFitsIn32Bits)));
        std::vector<Port> ports{TargetPort("socket", module->socket),
                                WireSinkPort("hold", module->hold),
                                WireSinkPort("bite", module->bite),
                                WireSourcePort("reset", module->reset)};
        return Instance{.module = std::move(module), .ports = std::move(ports)};
      });
  registry.Add("spi_flash", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<SpiFlash>(
        name, parameters.Required("size", kFlashSize),
        parameters.Required("clock_hz", kAtLeastOne));
    // A CPU whose boot ROM reads the window, and which drives nothing else,
    // needs the controller's registers nowhere on its bus.
    std::vector<Port> ports{
        TargetPort("socket", module->socket, /*required=*/false),
        TargetPort("xip", module->xip)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("virtio_blk", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<VirtioBlk>(
        name, parameters.Required("blocks", kDiskSectors));
    std::vector<Port> ports{TargetPort("cpu", module->cpu),
                            InitiatorPort("dma", module->dma),
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("virtio_console", [](const char* name, Parameters&) {
    auto module = std::make_unique<VirtioConsole>(name);
    std::vector<Port> ports{TargetPort("cpu", module->cpu),
                            InitiatorPort("dma", module->dma),
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("virtio_9p", [](const char* name, Parameters&) {
    auto module = std::make_unique<Virtio9p>(name);
    std::vector<Port> ports{TargetPort("cpu", module->cpu),
                            InitiatorPort("dma", module->dma),
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("virtio_fs", [](const char* name, Parameters&) {
    auto module = std::make_unique<VirtioFs>(name);
    std::vector<Port> ports{TargetPort("cpu", module->cpu),
                            InitiatorPort("dma", module->dma),
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("virtio_net", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<VirtioNet>(
        name, parameters.Optional("mac", kVirtioNetMac, kMacAddresses));
    std::vector<Port> ports{TargetPort("cpu", module->cpu),
                            InitiatorPort("dma", module->dma),
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("virtio_rng", [](const char* name, Parameters& parameters) {
    auto module =
        std::make_unique<VirtioRng>(name, parameters.Optional("seed", 1));
    std::vector<Port> ports{TargetPort("cpu", module->cpu),
                            InitiatorPort("dma", module->dma),
                            // A driver may poll the used ring and leave
                            // the line alone.
                            WireSourcePort("irq", module->irq,
                                           /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("watchdog", [](const char* name, Parameters&) {
    auto module = std::make_unique<Watchdog>(name);
    std::vector<Port> ports{
        TargetPort("socket", module->socket),
        WireSourcePort("irq", module->irq, /*required=*/false),
        WireSourcePort("bite", module->bite, /*required=*/false)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // The router is SCC's (Minres SystemC-Components), not ours. This adapter
  // sizes it and loads its address map from the parameters:
  //   inputs               how many masters it takes; one if left out
  //   outputs              how many targets it routes to
  //   out<N>.base, .size   the address range routed to output N
  // An access inside a range reaches that target at its offset from the base,
  // whichever input it came in by. The first input is the port `target`, and
  // the others are `in1`, `in2` and so on.
  registry.Add("router", [](const char* name, Parameters& parameters) {
    const std::uint64_t inputs = parameters.Optional("inputs", 1);
    const std::uint64_t outputs = parameters.Required("outputs");
    auto module = std::make_unique<scc::router<32>>(name, outputs, inputs);
    module->set_warn_on_address_error(true);
    std::vector<Port> ports;
    ports.reserve(inputs + outputs);
    for (std::uint64_t index = 0; index < inputs; ++index) {
      ports.push_back(TargetPort(
          index == 0 ? std::string{"target"} : "in" + std::to_string(index),
          module->target[index]));
    }
    for (std::uint64_t index = 0; index < outputs; ++index) {
      const std::string output = "out" + std::to_string(index);
      module->set_target_range(index, parameters.Required(output + ".base"),
                               parameters.Required(output + ".size"));
      ports.push_back(InitiatorPort(output, module->initiator[index]));
    }
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  return registry;
}

}  // namespace socpuppet
