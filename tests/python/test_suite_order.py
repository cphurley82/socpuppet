"""The order this suite's tests are handed out in.

ctest runs the suite on every core with pytest-xdist, which hands the tests
out in the order they were collected. A boot of real firmware takes most of
a minute, so those tests go first: started last, one of them would keep the
whole run waiting while every other core sat idle.

⚠️ This test sees something only in a run of the whole suite. ctest's three
entries each choose by marker, and none holds both this test and the boots, so
there it is skipped, and in CI only the `wheel` job, which chooses nothing, can
fail it (tools/test_wheel.py). So a new module of boots goes in BOOTS as it is
written: nothing nearer will say so.
"""

import pytest

# The modules whose tests boot OpenSBI, UEFI and Linux, or Zephyr on virtio.
BOOTS = {
    "test_fetched_images",
    "test_linux_boot_flash",
    "test_linux_command_boots",
    "test_linux_gpio",
    "test_linux_nvme",
    "test_linux_rtc",
    "test_iommu",
    "test_linux_boots",
    "test_opensbi_boots",
    "test_linux_root_on_the_drive",
    "test_uefi_boots",
    "test_ssh_over_the_cable",
    "test_this_machines_linux_mounts_the_ssd",
    "test_virtio_uefi",
    "test_virtio_zephyr",
}


def test_when_the_boots_are_collected_they_come_before_every_other_test(
    request,
):
    boots = [item.path.stem in BOOTS for item in request.session.items]
    if not any(boots):
        pytest.skip("the boots of OpenSBI, UEFI and Linux were not collected")

    assert boots == sorted(boots, reverse=True)
