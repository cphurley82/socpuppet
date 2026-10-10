/*
 * UCIe link: the registers.
 *
 * One end of the die-to-die link: UCIe's Link DVSEC, the reset and fault
 * registers it locates, and the sideband mailbox.
 *
 * Generated from regs/ucie_link.rdl by tools/regs.py. Do not edit: change the
 * register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_UCIE_LINK_H_
#define SOCPUPPET_REGS_UCIE_LINK_H_

/* How many bytes of address space the block takes. */
#define UCIE_LINK_SIZE 0x100U

/* PCIe's extended capability header. */
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER                     0x00U
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER_AT_RESET            0x00010023U
/* 0x0023, which says a designated vendor-specific capability. */
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER_CAPABILITY_ID_MASK  0x0000FFFFU
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER_CAPABILITY_ID_SHIFT 0U
/* The capability's version. */
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER_VERSION_MASK        0x000F0000U
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER_VERSION_SHIFT       16U
/* Where the next capability is. There is none. */
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER_NEXT_MASK           0xFFF00000U
#define UCIE_LINK_EXTENDED_CAPABILITY_HEADER_NEXT_SHIFT          20U

/* DVSEC header 1: whose capability it is. */
#define UCIE_LINK_DVSEC_HEADER_1                 0x04U
#define UCIE_LINK_DVSEC_HEADER_1_AT_RESET        0x1000D2DEU
/* 0xD2DE, which is the vendor number UCIe registered. */
#define UCIE_LINK_DVSEC_HEADER_1_VENDOR_ID_MASK  0x0000FFFFU
#define UCIE_LINK_DVSEC_HEADER_1_VENDOR_ID_SHIFT 0U
/* The capability's revision. */
#define UCIE_LINK_DVSEC_HEADER_1_REVISION_MASK   0x000F0000U
#define UCIE_LINK_DVSEC_HEADER_1_REVISION_SHIFT  16U
/* How long the capability is, in bytes: the whole block. */
#define UCIE_LINK_DVSEC_HEADER_1_LENGTH_MASK     0xFFF00000U
#define UCIE_LINK_DVSEC_HEADER_1_LENGTH_SHIFT    20U

/* DVSEC header 2: which of the vendor's capabilities it is. */
#define UCIE_LINK_DVSEC_HEADER_2                0x08U
#define UCIE_LINK_DVSEC_HEADER_2_AT_RESET       0x00000001U
/* ⚠️ Ours: public sources do not give UCIe's number for the link DVSEC. */
#define UCIE_LINK_DVSEC_HEADER_2_DVSEC_ID_MASK  0x0000FFFFU
#define UCIE_LINK_DVSEC_HEADER_2_DVSEC_ID_SHIFT 0U

/*
 * UCIe's link control. Both bits are an action, clear themselves, and read as
 * zero.
 */
#define UCIE_LINK_CONTROL                0x10U
/* Start link training. */
#define UCIE_LINK_CONTROL_START_TRAINING (1U << 0)
/* Retrain the link, from reset. */
#define UCIE_LINK_CONTROL_RETRAIN        (1U << 1)

/* UCIe's link status. */
#define UCIE_LINK_STATUS                     0x14U
/* The link is up. */
#define UCIE_LINK_STATUS_UP                  (1U << 0)
/* The link is being trained. */
#define UCIE_LINK_STATUS_TRAINING            (1U << 1)
/* The link has gone up or come down since this was cleared. */
#define UCIE_LINK_STATUS_CHANGED             (1U << 2)
/* The other die has reported an error nothing can be done about. */
#define UCIE_LINK_STATUS_UNCORRECTABLE_FATAL (1U << 3)

/* UCIe's link event notification: what raises `irq`. */
#define UCIE_LINK_EVENT_NOTIFICATION                0x18U
/* Interrupt while the status says the link has changed. */
#define UCIE_LINK_EVENT_NOTIFICATION_STATUS_CHANGED (1U << 0)

/*
 * The register locator: where the block of the link's own registers is. ⚠️
 * Its layout is ours.
 */
#define UCIE_LINK_REGISTER_LOCATOR              0x1CU
#define UCIE_LINK_REGISTER_LOCATOR_AT_RESET     0x00002001U
/* Which block it is. */
#define UCIE_LINK_REGISTER_LOCATOR_BLOCK_MASK   0x000000FFU
#define UCIE_LINK_REGISTER_LOCATOR_BLOCK_SHIFT  0U
/* Where the block starts, from the start of the capability. */
#define UCIE_LINK_REGISTER_LOCATOR_OFFSET_MASK  0xFFFFFF00U
#define UCIE_LINK_REGISTER_LOCATOR_OFFSET_SHIFT 8U

/* Which training state the link is in. ⚠️ The numbers are ours. */
#define UCIE_LINK_TRAINING_STATE             0x20U
/* Held in reset, as every link is for 4 ms after power-on. */
#define UCIE_LINK_TRAINING_STATE_RESET       0U
/* The sideband is being brought up. */
#define UCIE_LINK_TRAINING_STATE_SBINIT      1U
/* The mainband's parameters are being agreed. */
#define UCIE_LINK_TRAINING_STATE_MBINIT      2U
/* The mainband is being trained. */
#define UCIE_LINK_TRAINING_STATE_MBTRAIN     3U
/* The two ends are agreeing that the link is theirs to use. */
#define UCIE_LINK_TRAINING_STATE_LINKINIT    4U
/* The link is up, and carries the dies' traffic. */
#define UCIE_LINK_TRAINING_STATE_ACTIVE      5U
/*
 * Training failed, or the link was broken. Only a retrain leaves this state.
 */
#define UCIE_LINK_TRAINING_STATE_TRAIN_ERROR 6U

/* The reset this end drives on its own die. */
#define UCIE_LINK_DIE_RESET          0x24U
#define UCIE_LINK_DIE_RESET_AT_RESET 0x00000001U
/*
 * The die is held in reset. The other die lets it go by writing a zero here,
 * through its mailbox.
 */
#define UCIE_LINK_DIE_RESET_ASSERTED (1U << 0)

/* A way to break the link on purpose. Reads as zero. */
#define UCIE_LINK_FAULT_INJECTION       0x28U
/* Write a one to break the link. */
#define UCIE_LINK_FAULT_INJECTION_BREAK (1U << 0)

/* What the next access to the other end is to be. */
#define UCIE_LINK_MAILBOX_OPCODE                       0x40U
/* UCIe's opcode for it, which is five bits of a sideband packet. */
#define UCIE_LINK_MAILBOX_OPCODE_CODE_MASK             0x0000001FU
#define UCIE_LINK_MAILBOX_OPCODE_CODE_SHIFT            0U
/* Read a register of the other end. */
#define UCIE_LINK_MAILBOX_OPCODE_CODE_MEMORY_READ_32B  0U
/* Write one. */
#define UCIE_LINK_MAILBOX_OPCODE_CODE_MEMORY_WRITE_32B 1U

/* Which register of the other end: its offset in the block there. */
#define UCIE_LINK_MAILBOX_ADDRESS 0x48U

/* What to write. Reads as what the last read brought back. */
#define UCIE_LINK_MAILBOX_DATA 0x50U

/* Sends the access. Reads as zero. */
#define UCIE_LINK_MAILBOX_TRIGGER    0x58U
/* Write a one to send it. */
#define UCIE_LINK_MAILBOX_TRIGGER_GO (1U << 0)

/* How the last access went, and whether one is still on its way. */
#define UCIE_LINK_MAILBOX_STATUS                          0x5CU
/* How it went. */
#define UCIE_LINK_MAILBOX_STATUS_CODE_MASK                0x00000007U
#define UCIE_LINK_MAILBOX_STATUS_CODE_SHIFT               0U
/* The other end did it. */
#define UCIE_LINK_MAILBOX_STATUS_CODE_SUCCESS             0U
/* There is no such register at the other end, or it cannot be written. */
#define UCIE_LINK_MAILBOX_STATUS_CODE_UNSUPPORTED_REQUEST 2U
/* An access has been sent and not yet answered. */
#define UCIE_LINK_MAILBOX_STATUS_BUSY                     (1U << 8)

#endif /* SOCPUPPET_REGS_UCIE_LINK_H_ */
