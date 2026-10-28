/*
 * What Zephyr's pin control API wants of a SoC: the type of one pin's
 * setting. A socpuppet SoC has no pins to share between its blocks, so no
 * driver sets one; the type is here because a driver that can set pins,
 * SiFive's SPI controller's among them, includes the API all the same.
 */

#ifndef SOCPUPPET_PINCTRL_SOC_H_
#define SOCPUPPET_PINCTRL_SOC_H_

#include <stdint.h>

typedef uint32_t pinctrl_soc_pin_t;

#endif /* SOCPUPPET_PINCTRL_SOC_H_ */
