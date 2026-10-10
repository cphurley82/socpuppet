/*
 * One end of a socpuppet die-to-die link, in the style of UCIe: what the
 * firmware on its own die does with it.
 *
 * A chiplet is one chip built from several dies, and the link between two
 * of them is not there when the power comes on. It has to be trained, and
 * until it is, nothing crosses it. The other die's CPU is held in reset
 * meanwhile, because nothing it could reach would answer.
 *
 * So the firmware on this die does three things: it trains the link, it
 * waits for it, and it lets the other die go. The last of those is
 * Zephyr's reset API, `reset_line_deassert(link, UCIE_LINK_THE_OTHER_DIE)`,
 * because that is exactly what it is. The rest is here.
 *
 * The link's own registers are in docs/models/d2d-link.md in socpuppet.
 */

#ifndef SOCPUPPET_DRIVERS_UCIE_LINK_H_
#define SOCPUPPET_DRIVERS_UCIE_LINK_H_

#include <stdbool.h>
#include <stdint.h>

#include <zephyr/device.h>

/*
 * The reset line this end of the link drives, for Zephyr's reset API:
 * the CPU of the die at the other end. There is only the one.
 */
#define UCIE_LINK_THE_OTHER_DIE 0

/*
 * Trains the link and waits until it is up, sleeping on its interrupt
 * until it says so.
 *
 * Returns 0, or -ETIMEDOUT if the link never came up: UCIe holds a link
 * in reset for 4 ms before training can even begin, and a link that
 * cannot be trained ends in its error state instead.
 */
int ucie_link_train(const struct device *dev);

/*
 * Trains a link that has gone down, from the beginning, and waits until
 * it is up again. The other end is told to start over too. Returns as
 * ucie_link_train() does.
 */
int ucie_link_retrain(const struct device *dev);

/* Whether the link says it is up, and so whether anything can cross it. */
bool ucie_link_is_up(const struct device *dev);

/*
 * Sleeps until the link is no longer up, which is what a manager does
 * once the other die is running: there is nothing else for it to do
 * until something goes wrong.
 */
void ucie_link_wait_until_down(const struct device *dev);

#endif /* SOCPUPPET_DRIVERS_UCIE_LINK_H_ */
