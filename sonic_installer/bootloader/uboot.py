"""
Bootloader implementation for uboot based platforms
"""

import platform
import subprocess
import os
import re
from shlex import split
import click

from ..common import (
   HOST_PATH,
   IMAGE_DIR_PREFIX,
   IMAGE_PREFIX,
   run_command,
)
from .onie import OnieInstallerBootloader

class UbootBootloader(OnieInstallerBootloader):

    NAME = 'uboot'
    DEFAULT_IMAGE_SLOTS = (1, 2)
    ROOTFS_IMAGE_SLOTS = {
        'CTC-SONIC-1': (1, 3),
        'CTC-SONIC-2': (2, 4),
    }

    def _get_fw_env(self, name):
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "-n", name], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        return out.rstrip()

    def _get_current_rootfs_label(self):
        try:
            with open('/proc/cmdline', 'r', encoding='utf-8') as cmdline:
                match = re.search(r'root=LABEL=([^\s]+)', cmdline.read())
        except OSError:
            return None

        if match:
            return match.group(1)
        return None

    def _get_image_slots(self):
        rootfs_label = self._get_current_rootfs_label()
        return self.ROOTFS_IMAGE_SLOTS.get(rootfs_label, self.DEFAULT_IMAGE_SLOTS)

    def _get_image_entries(self):
        images = []
        for slot in self._get_image_slots():
            image = self._get_fw_env(f"sonic_version_{slot}")
            if IMAGE_PREFIX in image:
                images.append((slot, image))
        return images

    def get_installed_images(self):
        return [image for _, image in self._get_image_entries()]

    def get_next_image(self):
        images = self._get_image_entries()
        if not images:
            return ''

        next_slot = None
        for env_name in ('boot_once', 'boot_next'):
            image = self._get_fw_env(env_name)
            match = re.search(r'sonic_image_(\d+)', image)
            if match:
                next_slot = int(match.group(1))
                break

        if next_slot is not None:
            for slot, image in images:
                if slot == next_slot:
                    return image

        return images[0][1]

    def set_default_image(self, image):
        for slot, installed_image in self._get_image_entries():
            if image == installed_image:
                run_command(['/usr/bin/fw_setenv', 'boot_next', f"run sonic_image_{slot}"])
                break
        return True

    def set_next_image(self, image):
        for slot, installed_image in self._get_image_entries():
            if image == installed_image:
                run_command(['/usr/bin/fw_setenv', 'boot_once', f"run sonic_image_{slot}"])
                break
        return True

    def install_image(self, image_path):
        run_command(["bash", image_path])

    def remove_image(self, image):
        click.echo('Updating next boot ...')
        image_entries = self._get_image_entries()
        remove_slot = None
        fallback_slot = None

        for slot, installed_image in image_entries:
            if image == installed_image and remove_slot is None:
                remove_slot = slot
            elif fallback_slot is None:
                fallback_slot = slot

        if remove_slot is not None:
            if fallback_slot is not None:
                run_command(['/usr/bin/fw_setenv', 'boot_next', f"run sonic_image_{fallback_slot}"])
            run_command(['/usr/bin/fw_setenv', f'sonic_version_{remove_slot}', "NONE"])

        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX, 1)
        click.echo('Removing image root filesystem...')
        subprocess.call(['rm','-rf', HOST_PATH + '/' + image_dir])
        click.echo('Done')

    def verify_image_platform(self, image_path):
        return os.path.isfile(image_path)

    def set_fips(self, image, enable):
        fips = "1" if enable else "0"
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "linuxargs"], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        cmdline = out.strip()
        cmdline = re.sub('^linuxargs=', '', cmdline)
        cmdline = re.sub(r' sonic_fips=[^\s]', '', cmdline) + " sonic_fips=" + fips
        run_command(['/usr/bin/fw_setenv', 'linuxargs', cmdline])
        click.echo('Done')

    def get_fips(self, image):
        proc = subprocess.Popen(["/usr/bin/fw_printenv", "linuxargs"], text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        return 'sonic_fips=1' in out

    @classmethod
    def detect(cls):
        arch = platform.machine()
        return ("arm" in arch) or ("aarch64" in arch)
