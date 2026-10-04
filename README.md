# K2-OpenHost slot B for the K2 Pro T113

**English** · [Italiano](README.it.md)

> [!WARNING]
> **Experienced users only — use at your own risk.** K2-OpenHost voids the manufacturer's warranty and can damage the printer beyond repair, brick its firmware or, in case of malfunction, cause a fire. The authors accept no liability for damage to property or persons.
> In OpenHost mode the **nozzle and chamber cameras** cannot be managed by the T113 and must be rewired directly to the external Linux host, and the printer's **external USB port** cannot be used to print and stops working completely in gadget mode.
> Read the [disclaimer and hardware limitations](https://github.com/MzTechnology97/K2-OpenHost/blob/main/docs/en/DISCLAIMER.md) before using this.

> **Status: built and checked offline, never booted on a printer.** Nothing here has run on real hardware yet.

The K2 Pro T113 has two system slots, A and B: two kernel partitions (`bootA`/`bootB`) and two root filesystems (`rootfsA`/`rootfsB`). A Creality OTA update writes the inactive slot and switches two U-Boot variables. This package uses the same mechanism to put a K2-OpenHost system in **slot B** and leave **slot A exactly as it is**, as a fallback.

## What slot B is

The stock Creality system that slot A runs (1.1.0.94), with these changes:

| Change | Why |
| --- | --- |
| Writable layer in `/mnt/UDISK/.k2openhost/overlay` | `rootfs_data` is slot A's overlay partition; slot B never mounts, checks or formats it. |
| `k2oh-gadget` service | Puts USB0 in device mode and creates three Generic Serial functions (`0525:a4a6`, interfaces 00/01/02). |
| `k2oh-bridge` service | One bridge process per bus: `ttyGS0↔ttyS2` Main MCU, `ttyGS1↔ttyS3` Nozzle MCU, `ttyGS2↔ttyS5` RS-485/CFS/motors, 230400 8N1. It is the bridge validated on the reference printer, restarted by procd. |
| Disabled: Klipper, klipper_mcu, Moonraker, nginx, Creality UI/cloud apps (`app`), ADB, WebRTC camera, USB-stick OTA | The external host runs Klipper; ADB would take the USB controller; an OTA started from slot B would overwrite slot A. |
| `chamber_cam_power.sh` does nothing | On the K2 Pro its `restart` reads `usbc0/usb_host`, which switches USB0 back to host mode and drops all three channels. |
| `k2oh-slot` command | Shows and switches the boot slot. |

Kept: the stock kernel (it already has the USB gadget drivers), `mcu_update` (it starts the Main and Nozzle MCU applications at every boot, see below), `board_init`, network (Ethernet DHCP), SSH, logging. Any camera connects to the external host.

## Files

| File | Runs on | Does |
| --- | --- | --- |
| `build-slot-b.sh` | Linux (e.g. the CM5) | Builds `bootB.img` and `rootfsB.squashfs` from the stock OTA `kernel` and `rootfs`. |
| `install-slot-b.sh` | The printer, slot A | Checks, backs up the old slot B and the U-Boot environment, writes slot B, reads it back. Does not switch slot. |
| `rootfs/` | — | Files added to the stock root filesystem. |

### Build

Needs `fakeroot` and `squashfs-tools` (`apt-get download squashfs-tools && dpkg -x squashfs-tools_*.deb tools` works without root). Unpack `kernel` and `rootfs` from the stock `CR0CN200400C10_ota_img_V1.1.0.94.img` (a cpio archive), then:

```bash
./build-slot-b.sh --kernel kernel --rootfs rootfs --out out
```

The script refuses other stock versions unless `--allow-other-base` is given, checks that the services are disabled and that `rootfs_data` is left alone, and writes `SHA256SUMS` and `manifest.txt`.

### Install (not tested yet)

Copy `out/` to the printer (for example to `/mnt/UDISK/k2oh-slotb`) and, as root on slot A:

```sh
sh install-slot-b.sh --check   # checks only
sh install-slot-b.sh           # writes and verifies slot B
/mnt/UDISK/.k2openhost/bin/k2oh-slot boot-b && reboot
```

`boot-b` is a **trial boot**. At the start of slot B's boot, before anything else runs, the next boot is pointed back at slot A. If slot B does not come up, power cycle the printer and it returns to slot A. When slot B works, run `k2oh-slot commit` on it to keep it. `k2oh-slot boot-a` returns to slot A at any time.

Slot A's SSH `authorized_keys` are copied to slot B. Slot B's root password is the stock one.

## MCU firmware updates

The peripheral firmware lives in the system image, as `/usr/share/klipper/fw/F012/*.bin` for the K2 Pro. At every boot the stock `mcu_update` service:

1. handshakes the Main MCU (`ttyS2`) and Nozzle MCU (`ttyS3`) in their Creality loader and reads their version;
2. flashes any MCU whose version **differs** from the matching `.bin`, older or newer;
3. updates the extruder motor through the nozzle board's transparent mode, and the RS-485 motors, belt and RFID boards with `mcu_util_485`. The CFS is updated only when the OTA server starts it with `CFS=1` and `/tmp/cfs_update.json`, after stopping Klipper and power-cycling the MCU rail (`mcu_reset.sh`);
4. starts the MCU applications (`startup app`). This step is needed at every boot, so slot B keeps the service.

Jacob10383's `motor_updater.py` does the same in Python at boot from firmware shipped in his image: P2P at 115200 for the Main/Nozzle MCUs, RS-485 for motors and CFS, belt and RFID excluded. The protocols are documented in [K2-OpenHost Firmware Tools](https://github.com/MzTechnology97/k2-openhost-firmware-tools).

Consequences for slot B:

- Slot B carries the same firmware files as slot A, so booting either slot flashes nothing.
- Updating to a new Creality release means putting its `.bin` files in slot B (its writable layer is on UDISK, so slot A is untouched) and running the stock sequence with the bridges and the host Klipper stopped. Rebuilding slot B from the newer OTA does the same at the next boot.
- **Slot A flashes its own older files back at its next boot**, because the stock script reflashes on any difference.
- The external host cannot flash through the bridges as they are: the loaders talk at 115200, the bridges run the UARTs at 230400, and the gadget serial link does not carry baud changes. Updates run on the T113.
