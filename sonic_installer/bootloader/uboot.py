"""
Bootloader implementation for uboot based platforms
"""

import platform
import subprocess

import click
import os

from ..common import (
   HOST_PATH,
   IMAGE_DIR_PREFIX,
   IMAGE_PREFIX,
   run_command,
)
from .onie import OnieInstallerBootloader

class UbootBootloader(OnieInstallerBootloader):

    NAME = 'uboot'

    SONIC_IMAGE_MAX = 2

    def sonic_save_spi_env_to_emmc(self):
        click.echo('Sonic del last spi-flash env in emmc.')
        os.system("rm -rf /host/master_update_env_done")
        os.system("rm -rf /host/slaver_update_env_done")
        os.system("rm -rf /host/spi_flash_env_bck")
        
        proc = subprocess.Popen("hexdump -C /dev/mtd2 | grep 1220", shell=True, text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        if 'master' in out.rstrip():
            ha_status = 'master'
        elif 'slaver' in out.rstrip():
            ha_status = 'slaver'
        else:
            click.echo('Please setv serialno 0x1220 master/slaver in uboot!')
            return True
            
        os.system("mkdir /host/spi_flash_env_bck")
        os.system("dd if=/dev/mtd1 of=/host/spi_flash_env_bck/mtd1_data")
        os.system("dd if=/dev/mtd3 of=/host/spi_flash_env_bck/mtd3_data")
       
        if ha_status == 'master':
            click.echo('Master save spi-flash env to emmc complete!')
            os.system("mkdir /host/master_update_env_done")
        else:
            click.echo('Slaver save spi-flash env to emmc complete!')
            os.system("mkdir /host/slaver_update_env_done")
        
        os.system("sync;sync;sync")
        os.system("sleep 3")  # wait 3 seconds after sync
        
        return True
        
    def get_installed_images(self):
        images = []
        for idx in range(1, self.SONIC_IMAGE_MAX + 1):
            cmd = '/usr/bin/fw_printenv -n sonic_version_' + str(idx) + ' 2>/dev/null'
            proc = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE)
            (out, _) = proc.communicate()
            image = out.rstrip()
            if IMAGE_PREFIX in image:
                images.append(image)
            else:
                images.append('NONE')
        return images

    def get_next_image(self):
        images = self.get_installed_images()
        proc = subprocess.Popen("/usr/bin/fw_printenv -n boot_next", shell=True, text=True, stdout=subprocess.PIPE)
        (out, _) = proc.communicate()
        image = out.rstrip()
        next_image_index = 0
        for idx in range(1, self.SONIC_IMAGE_MAX + 1):
            if 'sonic_image_' + str(idx) in image:
                next_image_index = idx - 1
        next_image = images[next_image_index]
        return images[next_image_index]

    def set_default_image(self, image):
        images = self.get_installed_images()
        if image not in images:
            return False
        for idx in range(1, self.SONIC_IMAGE_MAX + 1):
            if image in images[idx - 1]:
                cmd = '/usr/bin/fw_setenv boot_next "run sonic_image_' + str(idx) + '"' + ' 2>/dev/null'
                run_command(cmd)
                break
        self.sonic_save_spi_env_to_emmc()
        return True

    def set_next_image(self, image):
        images = self.get_installed_images()
        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX)
        for idx in range(1, self.SONIC_IMAGE_MAX + 1):
            if image in images[idx - 1] or image_dir in images[idx - 1]:
                cmd = '/usr/bin/fw_setenv boot_once "run sonic_image_' + str(idx) + '"'
                run_command(cmd)
                break
        self.sonic_save_spi_env_to_emmc()
        return True

    def install_image(self, image_path):
        run_command("bash " + image_path)

    def remove_image(self, image):
        click.echo('Updating next boot ...')
        images = self.get_installed_images()
        rm_idx = 0
        next_idx = 0
        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX)
        for idx in range(1, self.SONIC_IMAGE_MAX + 1):
            if image in images[idx - 1]:
                rm_idx = idx
                break
        if rm_idx == 0:
            click.echo('Image not installed!')
            return
        for idx in range(1, self.SONIC_IMAGE_MAX + 1):
            if images[idx - 1] != 'NONE' and idx != rm_idx:
                next_idx = idx
                break
        if next_idx == 0:
            click.echo('Trying to remove the last image, break!')
            return
        cmd = '/usr/bin/fw_setenv boot_next "run sonic_image_' + str(next_idx) + '" 2>/dev/null'
        run_command(cmd)
        cmd = '/usr/bin/fw_setenv sonic_image_' + str(rm_idx) + ' "NONE" 2>/dev/null'
        run_command(cmd)
        cmd = '/usr/bin/fw_setenv sonic_version_' + str(rm_idx) + ' "NONE" 2>/dev/null'
        run_command(cmd)
        cmd = '/usr/bin/fw_setenv sonic_dir_' + str(rm_idx) + ' "NONE" 2>/dev/null'
        run_command(cmd)
        click.echo('Removing image root filesystem...')
        subprocess.call(['rm','-rf', HOST_PATH + '/' + image_dir])
        self.sonic_save_spi_env_to_emmc()
        click.echo('Done')

    @classmethod
    def detect(cls):
        arch = platform.machine()
        return ("arm" in arch) or ("aarch64" in arch)
