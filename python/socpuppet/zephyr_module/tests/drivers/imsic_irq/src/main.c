/*
 * irq_enable(), irq_disable() and irq_is_enabled() on the host, whose
 * interrupts arrive at an IMSIC as messages.
 *
 * The host has two devices with a wire for an interrupt, one on each die:
 * the watchdog on the compute die and the console's UART on the IO die.
 * Each wire goes to the APLIC of its own die, which sends a message to the
 * IMSIC for it. Enabling a number therefore has work to do in two places,
 * and has to pick the right APLIC of the two. These cases call the three
 * functions and read the controllers' own registers to see what was done.
 *
 * No interrupt is taken here: no device is asked to raise its line. That
 * a message arrives and a handler runs is what the shell's tests and the
 * watchdog's show.
 */

#include <stdbool.h>
#include <stdint.h>

#include <zephyr/devicetree.h>
#include <zephyr/irq.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>
#include <zephyr/ztest.h>

/* A device with a wire on each die, and where each wire goes. */
#define WATCHDOG DT_ALIAS(watchdog0)
#define CONSOLE  DT_CHOSEN(zephyr_console)

#define WATCHDOGS_NUMBER DT_IRQN(WATCHDOG)
#define CONSOLES_NUMBER  DT_IRQN(CONSOLE)
#define COMPUTE_APLIC    DT_REG_ADDR(DT_IRQ_INTC(WATCHDOG))
#define IO_APLIC         DT_REG_ADDR(DT_IRQ_INTC(CONSOLE))

/*
 * A number that is an identity of the IMSIC's and no device's wire, though
 * it is one an APLIC has a source for. The board hands such numbers out
 * from 16 up, so the build says if a device has come to have this one.
 */
#define NO_WIRES_NUMBER 20
#define NOT_THE_NUMBER_OF(idx, node)                                                               \
	BUILD_ASSERT(DT_IRQ_BY_IDX(node, idx, irq) != NO_WIRES_NUMBER,                             \
		     "A device has this number now: pick another that no device has.");
#define NO_INTERRUPT_OF(node) LISTIFY(DT_NUM_IRQS(node), NOT_THE_NUMBER_OF, (), node)
DT_FOREACH_STATUS_OKAY_NODE(NO_INTERRUPT_OF)

/*
 * An APLIC's registers, by the names the RISC-V interrupt specification
 * gives them. A source's own are an array, with source 1 first.
 */
#define SOURCECFG(source) (0x0004 + 4 * ((source) - 1))
#define SETIE(source)     (0x1E00 + 4 * ((source) / 32))
#define TARGET(source)    (0x3004 + 4 * ((source) - 1))
/* A source that asks for as long as its line is high. */
#define LEVEL_HIGH        6
/* The identity a source is sent on as, in its target register. */
#define IDENTITY_MASK     0x7FF

static bool is_enabled_at(mem_addr_t aplic, unsigned int source)
{
	return (sys_read32(aplic + SETIE(source)) & BIT(source % 32)) != 0;
}

static void all_off(void *fixture)
{
	ARG_UNUSED(fixture);

	irq_disable(WATCHDOGS_NUMBER);
	irq_disable(CONSOLES_NUMBER);
	irq_disable(NO_WIRES_NUMBER);
}

ZTEST(imsic_irq, test_enabling_a_wires_number_enables_its_identity_at_the_imsic)
{
	irq_enable(WATCHDOGS_NUMBER);

	zassert_true(irq_is_enabled(WATCHDOGS_NUMBER));
}

ZTEST(imsic_irq, test_disabling_a_wires_number_disables_its_identity_at_the_imsic)
{
	irq_enable(WATCHDOGS_NUMBER);

	irq_disable(WATCHDOGS_NUMBER);

	zassert_false(irq_is_enabled(WATCHDOGS_NUMBER));
}

ZTEST(imsic_irq, test_a_wire_on_the_compute_die_is_enabled_at_that_dies_aplic_and_not_the_other)
{
	irq_enable(WATCHDOGS_NUMBER);

	zassert_true(is_enabled_at(COMPUTE_APLIC, WATCHDOGS_NUMBER));
	zassert_false(is_enabled_at(IO_APLIC, WATCHDOGS_NUMBER));
}

ZTEST(imsic_irq, test_a_wire_on_the_io_die_is_enabled_at_that_dies_aplic_and_not_the_other)
{
	irq_enable(CONSOLES_NUMBER);

	zassert_true(is_enabled_at(IO_APLIC, CONSOLES_NUMBER));
	zassert_false(is_enabled_at(COMPUTE_APLIC, CONSOLES_NUMBER));
}

ZTEST(imsic_irq, test_disabling_a_wires_number_disables_it_at_its_aplic)
{
	irq_enable(WATCHDOGS_NUMBER);

	irq_disable(WATCHDOGS_NUMBER);

	zassert_false(is_enabled_at(COMPUTE_APLIC, WATCHDOGS_NUMBER));
}

ZTEST(imsic_irq, test_a_wire_is_sent_on_as_the_identity_of_its_own_number)
{
	irq_enable(WATCHDOGS_NUMBER);

	zassert_equal(sys_read32(COMPUTE_APLIC + TARGET(WATCHDOGS_NUMBER)) & IDENTITY_MASK,
		      WATCHDOGS_NUMBER);
}

ZTEST(imsic_irq, test_a_wire_is_set_to_ask_for_as_long_as_it_is_high)
{
	irq_enable(WATCHDOGS_NUMBER);

	zassert_equal(sys_read32(COMPUTE_APLIC + SOURCECFG(WATCHDOGS_NUMBER)), LEVEL_HIGH);
}

ZTEST(imsic_irq, test_a_number_that_is_no_wire_is_enabled_at_the_imsic_and_at_neither_aplic)
{
	irq_enable(NO_WIRES_NUMBER);

	zassert_true(irq_is_enabled(NO_WIRES_NUMBER));
	zassert_false(is_enabled_at(COMPUTE_APLIC, NO_WIRES_NUMBER));
	zassert_false(is_enabled_at(IO_APLIC, NO_WIRES_NUMBER));
}

ZTEST(imsic_irq, test_the_machine_timers_number_which_zephyr_enabled_reads_as_enabled)
{
	/*
	 * A number below sixteen is a line of the CPU's own and no identity,
	 * and is still asked of Zephyr's own function.
	 */
	zassert_true(irq_is_enabled(DT_IRQN(DT_NODELABEL(compute_timer))));
}

ZTEST_SUITE(imsic_irq, NULL, NULL, all_off, all_off, NULL);
