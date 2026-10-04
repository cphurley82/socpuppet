-- A QBox platform for the ISS spike: one RISC-V CPU, RAM, a 16550 UART,
-- the interrupt controller and the timer, at the addresses of QEMU's
-- `virt` machine. It is the same stage the other candidates perform on,
-- built from QBox's own components instead of socpuppet's.
--
-- Chosen through the environment:
--   SPIKE_XLEN   64 (the default) or 32
--   SPIKE_IMAGE  the flat binary to put at the start of RAM
--   SPIKE_MODE   "deterministic" (the default): QEMU runs as a coroutine
--                on the SystemC thread and counts instructions for time.
--                "threaded": QEMU's own threads, running flat out.

local xlen = tonumber(os.getenv("SPIKE_XLEN") or "64")
local image = os.getenv("SPIKE_IMAGE")
local threaded = os.getenv("SPIKE_MODE") == "threaded"

local RAM_BASE = 0x80000000

platform = {
    quantum_ns = 1000000;
    moduletype = "Container";

    router = {
        moduletype = "router";
    },

    qemu_inst_mgr = {
        moduletype = "QemuInstanceManager";
    },

    qemu_inst = {
        moduletype = "QemuInstance";
        args = {"&platform.qemu_inst_mgr", xlen == 64 and "RISCV64" or "RISCV32"};
        tcg_mode = threaded and "MULTI" or "COROUTINE";
        sync_policy = threaded and "multithread-unconstrained" or "tlm2";
        icount = not threaded;
    },

    plic_0 = {
        moduletype = "plic_sifive";
        args = {"&platform.qemu_inst"};
        mem = {address = 0x0c000000, size = 0x600000, bind = "&router.initiator_socket"};
        num_sources = 96;
        num_priorities = 7;
        priority_base = 0x0;
        pending_base = 0x1000;
        enable_base = 0x2000;
        enable_stride = 0x80;
        context_base = 0x200000;
        context_stride = 0x1000;
        aperture_size = 0x600000;
        hart_config = "M";
    },

    swi_0 = {
        moduletype = "riscv_aclint_swi";
        args = {"&platform.qemu_inst", "&platform.cpu_0"};
        mem = {address = 0x2000000, size = 0x4000, bind = "&router.initiator_socket"};
        num_harts = 1;
    },

    mtimer_0 = {
        moduletype = "riscv_aclint_mtimer";
        args = {"&platform.qemu_inst"};
        mem = {address = 0x2004000, size = 0x8000, bind = "&router.initiator_socket"};
        timecmp_base = 0x0;
        time_base = 0xbff8;
        provide_rdtime = true;
        aperture_size = 0x10000;
        num_harts = 1;
    },

    ram_0 = {
        moduletype = "gs_memory";
        target_socket = {address = RAM_BASE, size = 0x10000000, bind = "&router.initiator_socket"};
    },

    uart_0 = {
        moduletype = "uart_16550";
        args = {"&platform.qemu_inst"};
        mem = {address = 0x10000000, size = 0x100, bind = "&router.initiator_socket"};
        irq_out = {bind = "&plic_0.irq_in_10"};
        regshift = 0;
        baudbase = 3686400;
    },

    load = {
        moduletype = "loader";
        initiator_socket = {bind = "&router.target_socket"};
        {bin_file = image, address = RAM_BASE};
    },

    cpu_0 = {
        moduletype = xlen == 64 and "cpu_riscv64" or "cpu_riscv32";
        args = {"&platform.qemu_inst", 0};
        mem = {bind = "&router.target_socket"};
        irq_in_7 = {bind = "&mtimer_0.timer_irq_0"};
        resetvec = RAM_BASE;
        pmp = true;
    },
};
