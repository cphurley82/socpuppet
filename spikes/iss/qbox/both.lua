-- Two boards in one QBox process, one 64-bit and one 32-bit, each with its
-- own QEMU instance, router, RAM and UART. This is the spike's question
-- about mixed word sizes, asked of QBox on its own.
--
--   SPIKE_IMAGE_64, SPIKE_IMAGE_32   the flat binary for each board

local RAM_BASE = 0x80000000

local function board(suffix, target, cpu_type, image)
    -- An argument names a component from the top; a binding names it from
    -- inside the platform.
    local inst = "&platform.qemu_inst" .. suffix
    local router = "&router" .. suffix
    platform["router" .. suffix] = {
        moduletype = "router";
    }
    platform["qemu_inst" .. suffix] = {
        moduletype = "QemuInstance";
        args = {"&platform.qemu_inst_mgr" .. suffix, target};
        tcg_mode = "COROUTINE";
        sync_policy = "tlm2";
        icount = true;
    }
    platform["qemu_inst_mgr" .. suffix] = {
        moduletype = "QemuInstanceManager";
    }
    platform["ram" .. suffix] = {
        moduletype = "gs_memory";
        target_socket = {address = RAM_BASE, size = 0x10000000, bind = router .. ".initiator_socket"};
    }
    platform["uart" .. suffix] = {
        moduletype = "uart_16550";
        args = {inst};
        mem = {address = 0x10000000, size = 0x100, bind = router .. ".initiator_socket"};
        regshift = 0;
        baudbase = 3686400;
    }
    platform["clint" .. suffix] = {
        moduletype = "gs_memory";
        target_socket = {address = 0x2000000, size = 0x10000, bind = router .. ".initiator_socket"};
    }
    platform["plic" .. suffix] = {
        moduletype = "gs_memory";
        target_socket = {address = 0x0c000000, size = 0x600000, bind = router .. ".initiator_socket"};
    }
    platform["load" .. suffix] = {
        moduletype = "loader";
        initiator_socket = {bind = router .. ".target_socket"};
        {bin_file = image, address = RAM_BASE};
    }
    platform["cpu" .. suffix] = {
        moduletype = cpu_type;
        args = {inst, 0};
        mem = {bind = router .. ".target_socket"};
        resetvec = RAM_BASE;
        pmp = true;
    }
end

platform = {
    quantum_ns = 1000000;
    moduletype = "Container";
}
board("_64", "RISCV64", "cpu_riscv64", os.getenv("SPIKE_IMAGE_64"))
board("_32", "RISCV32", "cpu_riscv32", os.getenv("SPIKE_IMAGE_32"))
