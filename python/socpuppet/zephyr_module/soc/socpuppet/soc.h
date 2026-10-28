/*
 * What a driver gets when it includes <soc.h>: the definitions that are
 * particular to one SoC. Everything a driver needs to know about a
 * socpuppet SoC is in the devicetree, and this file only says where to
 * look for what a driver of Zephyr's asks it by name.
 *
 * The file is here because some of Zephyr's drivers include it whether
 * they use it or not, its NVMe driver among them.
 */

#ifndef SOCPUPPET_SOC_H_
#define SOCPUPPET_SOC_H_

/*
 * The clock SiFive's peripheral drivers count in, which a SiFive SoC
 * defines here. A socpuppet board gives its SPI controller a fixed clock in
 * the devicetree, and this is that clock's rate, read from the SPI
 * controller's node: a board with no such node has no such rate here.
 */
#define SIFIVE_PERIPHERAL_CLOCK_FREQUENCY                                                          \
	DT_PROP(DT_CLOCKS_CTLR(DT_COMPAT_GET_ANY_STATUS_OKAY(sifive_spi0)), clock_frequency)

#endif /* SOCPUPPET_SOC_H_ */
