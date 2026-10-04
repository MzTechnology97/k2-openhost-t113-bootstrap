# K2-OpenHost T113 bootstrap

**English** · [Italiano](README.it.md)

> [!WARNING]
> **Experienced users only — use at your own risk.** K2-OpenHost voids the manufacturer's warranty and can damage the printer beyond repair, brick its firmware or, in case of malfunction, cause a fire. The authors accept no liability for damage to property or persons.
> In OpenHost mode the **nozzle and chamber cameras** cannot be managed by the T113 and must be rewired directly to the external Linux host, and the printer's **external USB port** cannot be used to print and stops working completely in gadget mode.
> Read the [disclaimer and hardware limitations](https://github.com/MzTechnology97/K2-OpenHost/blob/main/docs/en/DISCLAIMER.md) before using this.

> **Status: built and tested offline, not yet booted on a printer.** Every piece below was checked on the reference CM5 (builds, file-by-file comparisons, the printer's own ARM binaries and Python in a chroot, real downloads from Creality and GitHub). Writing slot B, booting it and flashing MCUs have not run on hardware yet.

> [!IMPORTANT]
> **Firmware version.** This work was prepared and tested on the K2 Pro stock firmware **1.1.0.94**, the version on the reference printer. Newer Creality releases are accepted: slot B is built from them only when the boot scripts it changes are identical to the reviewed ones (true for 1.1.7.0), and the installer warns and asks for confirmation. **On any firmware other than 1.1.0.94, the correct operation of the bootstrap and of the T113 USB gadget (OTG) mode is not guaranteed.**

This repository is part of [K2-OpenHost](https://github.com/MzTechnology97/K2-OpenHost):

| Repository | Role |
| --- | --- |
| **k2-openhost-t113-bootstrap** (this one) | The printer side: the slot B system for the T113, its installer, `k2oh-slot`, `k2oh-setup`, `k2oh-mcu-fw`. |
| [k2-openhost-installer-helper](https://github.com/MzTechnology97/k2-openhost-installer-helper) | The external host. Its menu (T113 section) clones this repository and runs the whole bootstrap over SSH. |
| [kalico-k2pro](https://github.com/MzTechnology97/kalico-k2pro) | Kalico for the K2 Pro on the external host. |
| [k2-pro-custom-firmware](https://github.com/MzTechnology97/k2-pro-custom-firmware) | Fork of Jacob10383's K2 firmware: K2 extras source and history; links here for the OpenHost T113 side. |
| [k2-openhost-firmware-tools](https://github.com/MzTechnology97/k2-openhost-firmware-tools) | Peripheral firmware research and read-only probes (protocols, `cfs_update.json` format). |

This turns the printer's T113 board into a ready K2-OpenHost bridge: USB gadget with the three K2 buses, HelixScreen on the printer screen talking to Moonraker on your external host, and a manual tool for Creality MCU, motor and CFS firmware updates. It goes into **slot B**. **Slot A**, the system the printer runs today, is never written and stays one command or one power cycle away.

## Contents

1. [How it works](#how-it-works)
2. [Requirements](#requirements)
3. [Install, step by step](#install-step-by-step)
4. [Trial boot, keep, go back](#trial-boot-keep-go-back)
5. [What runs in slot B](#what-runs-in-slot-b)
6. [Updating MCU, motor and CFS firmware](#updating-mcu-motor-and-cfs-firmware)
7. [Why Creality's updater and not Jacob's](#why-creality-s-updater-and-not-jacob-s)
8. [Troubleshooting](#troubleshooting)
9. [Removing it](#removing-it)
10. [Reference](#reference)

## How it works

The T113 has two system slots: two kernel partitions (`bootA`, `bootB`) and two root filesystems (`rootfsA`, `rootfsB`). Creality's own OTA updates write the inactive slot and switch two U-Boot variables, `boot_partition` and `root_partition`. The bootstrap uses exactly that mechanism.

```text
                          eMMC of the T113
 ┌───────────┬───────────┬─────────────┬─────────────┬──────────────┬───────────────────┐
 │ bootA     │ bootB     │ rootfsA     │ rootfsB     │ rootfs_data  │ UDISK (27 GB)     │
 │ stock     │ stock     │ stock       │ K2-OpenHost │ slot A's     │ shared: slot A    │
 │ kernel    │ kernel    │ system      │ system      │ changes      │ data + .k2openhost│
 └───────────┴───────────┴─────────────┴─────────────┴──────────────┴───────────────────┘
   slot A ─────────────────── untouched ──────────────────────┘         slot B's own
                                                                        writable layer
```

Slot B is a **stock Creality system**: by default the same release slot A runs, otherwise the latest in Creality's index or one you choose. It is downloaded from Creality's CDN on your host and changed only where K2-OpenHost needs it. No Creality file is redistributed by this project. Slot B keeps its writable layer in `/mnt/UDISK/.k2openhost/overlay`, so it never mounts, checks or formats slot A's `rootfs_data`, and it never formats, checks or wipes UDISK.

The whole install runs from the external host (`helper.sh`, menu **T113**), over SSH to the printer:

```text
external host (helper.sh)                              printer T113, running slot A
 1. asks the printer IP, finds its own IP
 2. checks slot A over SSH (read-only)  ──────────────▶ slot, U-Boot env, version
 3. downloads the Creality OTA (slot A's release), checks MD5
 4. builds bootB.img + rootfsB.squashfs
 5. downloads HelixScreen for the K2
 6. uploads everything, checks SHA-256  ──────────────▶ /mnt/UDISK/k2oh-slotb
 7. runs install-slot-b.sh  ──────────────────────────▶ backs up env + old slot B,
                                                         writes slot B, reads it back,
                                                         saves host IP, Wi-Fi, SSH keys
 8. trial boot  ──────────────────────────────────────▶ boots slot B once
                                                         first boot: HelixScreen install
```

## Requirements

| What | Detail |
| --- | --- |
| Printer | **Creality K2 Pro only** (Creality model `F012`, board `CR0CN200400C10`, checked on the printer), slot A on stock firmware (prepared and tested on **1.1.0.94**; newer releases accepted with a warning, not guaranteed), root SSH enabled (stock password `creality_2024`). |
| Network | Printer and host on the same network (Ethernet or Wi-Fi) for the install. Afterwards HelixScreen uses the network to reach Moonraker. |
| External host | Installed with this helper (Kalico, Moonraker, Mainsail), Debian-based, internet access, about 1 GB free. |
| Cable | The printer's service Micro-USB port to a USB port of the host. |
| Cameras | Connected to the host (they cannot work through the T113 in gadget mode). |
| Printer UDISK | About 1.5 GB free (old slot B backup, images, HelixScreen). |

## Install, step by step

1. **On the printer:** enable root access in the screen settings if needed, note its IP address (screen: network settings).
2. **On the host**, in the helper directory:

   ```bash
   ./helper.sh
   ```

   choose **23) Install the T113 bootstrap** (or run `./helper.sh t113 install`).
3. **Confirm** the warning, then enter:
   - the **printer IP**;
   - the **host IP** as the printer sees it. The helper proposes the address of the interface that reaches the printer; press Enter to accept it.

   Both are saved in `~/.k2-openhost-installer-helper/t113.conf`.
4. **Log in** with the printer's root password when asked. One SSH connection is kept open, so you type it once.
5. The helper **checks the printer** (read-only):
   - it must be a **Creality K2 Pro**: model `F012` and board `CR0CN200400C10`, read from the printer itself;
   - slot A must be the running slot, and the boot environment must point at it;
   - slot A's firmware release is read and shown.

   Anything else stops the install before anything is written. `install-slot-b.sh` repeats the same checks on the printer, and `k2oh-mcu-fw` refuses to run on any other model.
6. It proposes the **Creality release to build slot B from**: slot A's release when Creality still lists it, otherwise the latest; you can type another one. A release other than 1.1.0.94 shows a warning (bootstrap and OTG mode not guaranteed) and needs confirmation. A release different from slot A's means each slot reflashes the boards to its own files when it boots.
7. It installs `fakeroot` and `squashfs-tools` on the host (sudo), clones this repository, **downloads that Creality OTA** (130–145 MB) from Creality's CDN, checks kernel and rootfs against the image's own MD5 list, and **builds slot B**. The build stops if any expected change is missing or if the stock boot scripts slot B changes differ from the reviewed ones.
8. Answer **yes** to install HelixScreen (recommended): the helper downloads the latest K2 release from GitHub.
9. The files are **uploaded** to `/mnt/UDISK/k2oh-slotb` on the printer and checked by SHA-256.
10. `install-slot-b.sh --check` runs on the printer: nothing is written yet.
11. **Confirm** to write slot B. The printer saves the U-Boot environment and the old slot B to `/mnt/UDISK/.k2openhost/backup/<date>/`, writes `bootB` and `rootfsB`, reads them back, and prepares slot B's writable layer:
    - slot A's SSH `authorized_keys` and saved Wi-Fi networks are copied;
    - the host IP is saved in `/mnt/UDISK/.k2openhost/k2openhost.conf`;
    - the HelixScreen archive is kept for the first boot.
12. Slot A still boots by default. Continue with the trial boot below.

## Trial boot, keep, go back

| Action | Menu | Command | What it does |
| --- | --- | --- | --- |
| Trial boot | 25 | `./helper.sh t113 boot-b` | Sets slot B for the next boot with a trial flag and reboots the printer. |
| Keep slot B | 26 | `./helper.sh t113 commit` | Run on slot B once it works: slot B becomes the default. |
| Back to slot A | 27 | `./helper.sh t113 boot-a` | Slot A at the next boot, then reboot. |
| Status | 24 | `./helper.sh t113 status` | Running slot, next boot, trial flag, setup, HelixScreen. |

**How the trial boot protects you:** at the very start of slot B's boot, before any service, the boot environment is pointed back at slot A. If slot B hangs, crashes or you cannot reach it, **power cycle the printer and it returns to slot A**. Only `commit`, run on a working slot B, makes slot B the default.

On the printer the same actions are `k2oh-slot status | boot-b | commit | boot-a` (`/mnt/UDISK/.k2openhost/bin/k2oh-slot` from slot A).

After the trial boot:

1. Connect the service Micro-USB cable to the host if it is not connected.
2. Check that Klipper on the host connects (Mainsail shows the printer ready). The host's start gate waits up to 60 s for the three gadget channels.
3. Check the screen: the first boot installs HelixScreen (about a minute), already pointed at your host.
4. Run **26) Keep slot B**.

## What runs in slot B

| Part | Detail |
| --- | --- |
| `k2oh-gadget` | Puts USB0 in device mode and creates three Generic Serial functions (`0525:a4a6`, interfaces 00/01/02), as the host udev rules expect. |
| `k2oh-bridge` | One bridge process per bus, restarted by procd: `ttyGS0↔ttyS2` Main MCU, `ttyGS1↔ttyS3` Nozzle MCU, `ttyGS2↔ttyS5` RS-485/CFS/motors, 230400 8N1. It is the bridge validated on the reference printer. |
| `mcu_update` (stock) | Kept: at every boot it starts the Main and Nozzle MCU applications (they power up in Creality's loader). It also reflashes any board whose version differs from slot B's firmware files. |
| `k2oh-wifi` | Starts `wpa_supplicant` and `udhcpc` like Creality's `wifi-server` did, with the networks copied from slot A. Ethernet works as in stock. |
| `k2oh-firstboot` / `k2oh-setup` | First boot: installs HelixScreen from the prepared archive and points it at `HOST_IP:7125`. Retried at each boot until it succeeds. `k2oh-setup --host <IP>` changes the host later (menu 28). |
| HelixScreen | The touch UI on the printer screen, connected to Moonraker on the host. |
| Disabled | Creality Klipper, klipper_mcu, Moonraker, nginx, UI/cloud apps (`app`), ADB (it would take the USB controller), WebRTC camera, USB-stick OTA (an OTA from slot B would overwrite slot A), factory reset `wipe_data` (it deletes most of UDISK). |
| `chamber_cam_power.sh` | Does nothing: on the K2 Pro its `restart` switches USB0 back to host mode and drops all three channels. |
| Protected | Slot A's `rootfs_data` is never mounted, checked or formatted. UDISK is only mounted (no `mkfs`, no `e2fsck`, `parts_clean` ignored). |

Slot B's root password is the stock one (`creality_2024`) even if you changed slot A's.

## Updating MCU, motor and CFS firmware

Firmware updates are **manual on purpose**. Run them from slot B, with the printer idle.

### The short way: latest release

From the host: menu **30) Update MCU firmware** (`./helper.sh t113 mcu-fw update`), or on the printer:

```sh
k2oh-mcu-fw update          # add --cfs to include the CFS units
```

It looks up the **latest** release in Creality's index, downloads it (only the firmware files are kept), stages it in slot B, shows which boards would change and asks **"Flash the boards now?"**. Answer no and nothing is flashed now; the staged files are flashed at slot B's next boot, or with `k2oh-mcu-fw apply`, or dropped with `k2oh-mcu-fw unstage`. Answer yes and it runs `apply` with all its checks (stop Klipper on the host first).

### What gets updated

The K2 Pro firmware set in a Creality release (`/usr/share/klipper/fw/F012` and `fw/cfs`):

| Board | Bus | File example (1.1.7.0) |
| --- | --- | --- |
| Main MCU | ttyS2, direct | `mcu0_120_G32-mcu0_001_000.bin` |
| Nozzle MCU | ttyS3, direct | `noz0_130_G30-noz0_021_000.bin` |
| Extruder motor | through the nozzle board | `mot2_022_C30-mot2_002_081.bin` |
| X/Y closed-loop motors | RS-485 | `motor/mot2_023_C30-mot2_002_081.bin` |
| Belt, RFID boards | RS-485 | `belt/…`, `rfid/rfd0_010_G21-rfd0_000_010.bin` |
| CFS units | RS-485 | `cfs/cfs0_050_G32-cfs0_000_153.bin` (one file per hardware variant) |

### Step by step

On the printer (`ssh root@<printer>`), or from the host with `./helper.sh t113 mcu-fw <command>`:

1. **See what Creality has released:**

   ```sh
   k2oh-mcu-fw list
   ```

   This reads Creality's public firmware index. No account is needed and no printer data is sent.
2. **Download a release** (default: the latest):

   ```sh
   k2oh-mcu-fw download 1.1.7.0
   ```

   The OTA image (about 145 MB) comes from Creality's CDN. Its rootfs is checked against the image's own MD5 list and read in place (the T113 has no loop devices, nothing is mounted). Only the firmware files are kept, in `/mnt/UDISK/.k2openhost/mcu-fw/1.1.7.0/` with a SHA-256 manifest, and the image is deleted.
3. **Stage it:**

   ```sh
   k2oh-mcu-fw stage 1.1.7.0
   k2oh-mcu-fw status
   ```

   This replaces slot B's firmware files and lists which boards would change.
4. **Stop Klipper on the host:**

   ```bash
   sudo systemctl stop klipper
   ```

   The MCU power is cycled during the update.
5. **Flash:**

   ```sh
   k2oh-mcu-fw apply            # Main, Nozzle, extruder, motors, belt, RFID
   k2oh-mcu-fw apply --cfs      # the same, then the CFS units
   ```

   `apply` refuses to run while Moonraker on the host reports Klipper `ready` or `startup` (it reads `MOONRAKER_URL` from `k2openhost.conf`). It asks you to type `flash`. Then:
   1. it stops the bridges;
   2. it power-cycles the MCU rail (`mcu_reset.sh`);
   3. it runs Creality's `mcu_update`;
   4. with `--cfs`, it runs the CFS pass below;
   5. it starts the bridges and prints the log and the new versions.
6. **Start Klipper on the host again:**

   ```bash
   sudo systemctl start klipper
   ```

   `k2oh-mcu-fw unstage` puts slot B's original files back.

**Note:** slot A reflashes its own release's files at its next boot, because the stock script flashes on any version difference. Booting slot A after an update downgrades the boards again.

### How the CFS pass works

Creality's updater flashes a CFS only when `/tmp/cfs_update.json` lists it. Its format was recovered from `mcu_util_485`:

```json
{"CFSs": [{"uuid": "xx xx xx xx xx xx xx xx xx xx xx xx", "fw": "/usr/share/klipper/fw/cfs/cfs0_050_G32-cfs0_000_153.bin"}]}
```

- `uuid` is the unit's 12-byte UniID, lowercase hex separated by spaces. The tool compares the first 35 characters exactly.
- `fw` is the file it opens.

`apply --cfs` never guesses either value:

1. The first pass (step 5) power-cycles the MCUs. Creality's tool then finds each CFS in its loader and writes its UniID and loader identity (`cfs0_050_G32-cfs0_000_113`) to `/tmp/.485_mcu_version`.
2. For each unit, `k2oh-mcu-fw` picks the file whose **hardware token matches exactly**. This matters: in 1.1.7.0 the G30 and G32 variants have different firmware (150 and 153). Units without exactly one matching file, or already up to date, are skipped.
3. It writes `/tmp/cfs_update.json`, power-cycles again and runs `CFS=1 mcu_update`, as Creality's OTA server does. `mcu_util_485` writes only to units whose UniID matches.

If the first pass reports no CFS in loader mode, nothing is flashed. A CFS left in loader mode is started again by Kalico's Box stack (`box_addr`) at the next Klipper start.

## Why Creality's updater and not Jacob's

Jacob10383's `motor_updater.py` is a careful open re-implementation of the same protocols and a good reference. For the K2 Pro, slot B uses Creality's own tools:

- **They are the tools validated for this hardware.** `mcu_util`, `mcu_util_485` and `/etc/init.d/mcu_update` ship with the K2 Pro firmware and run on every stock boot and OTA. Using them reproduces an official update exactly, including its known failure and recovery behaviour.
- **They are already in slot B**, at the same version slot A runs, so both slots flash the same way and there is no extra code to maintain.
- **They match the K2 Pro topology.** `motor_updater.py` targets "K2/K2-Plus style printers": it expects four RS-485 motors (the K2 Pro has two, plus the extruder through the nozzle board), it skips belt and RFID boards, and its power-rail handling (`gpio140`, "kernel boots with rail OFF") follows Jacob's own kernel, not the stock one.
- **They handle the CFS the way Creality does**, through `cfs_update.json` and the stock power-cycle sequence, with the exact hardware-variant selection described above.

What Creality's tools lack: they are closed binaries, they log less, and they reflash on any difference (downgrades included). `motor_updater.py` gives finer control (`--versions-only`, `--one <uuid>`). It remains an option to evaluate later, especially together with the K2-OpenHost Firmware Tools work.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| The printer does not come back after the trial boot | Power cycle it: it returns to slot A. Look at `/mnt/UDISK/.k2openhost/setup.log` from slot A. |
| Klipper on the host does not connect | `./helper.sh doctor` checks the three channels. On the printer: `logread \| grep -E "k2oh\|bridge"`, `cat /sys/kernel/config/usb_gadget/g1/UDC`. |
| The screen stays on the boot logo | `k2oh-setup status`, `cat /mnt/UDISK/.k2openhost/setup.log`; run `k2oh-setup` again. |
| HelixScreen cannot reach Moonraker | Wrong host IP: menu 28 or `k2oh-setup --host <IP>`. Check that the printer reaches the host on port 7125. |
| No network in slot B over Wi-Fi | Slot A had no saved network, or it was added later: set Wi-Fi from HelixScreen, or copy `/etc/wifi/wpa_supplicant/wpa_supplicant.conf`. |
| `apply` refuses to run | Stop Klipper on the host (`sudo systemctl stop klipper`). |
| An update failed half-way | Run `k2oh-mcu-fw apply` again: Creality's updater restarts each transfer from the beginning. Read `/tmp/mcu_update.log`. |

## Removing it

1. `./helper.sh t113 boot-a` (menu 27). The printer runs slot A as before.
2. Optional, from slot A: `rm -rf /mnt/UDISK/.k2openhost` removes slot B's writable layer, backups and downloaded firmware. Slot B's partitions stay as they are until a Creality OTA writes them.

## Reference

### Files in this directory

| File | Runs on | Does |
| --- | --- | --- |
| `build-slot-b.sh` | host | Builds `bootB.img` and `rootfsB.squashfs` from the stock `kernel` and `rootfs`; warns on releases other than 1.1.0.94 and refuses when the stock boot scripts it changes differ (`--force-preinit` to override after a review). |
| `fetch-stock-ota.py` | host | Lists Creality's releases, downloads one (or the latest), checks MD5, keeps `kernel` and `rootfs`. |
| `install-slot-b.sh` | printer, slot A | `--check` / write slot B, backups, setup files. |
| `rootfs/` | — | Files added to the stock root filesystem. |
| [`scripts/t113.sh`](https://github.com/MzTechnology97/k2-openhost-installer-helper/blob/main/scripts/t113.sh) (installer helper) | host | The helper's T113 commands; clones this repository to `~/k2-openhost-t113-bootstrap`. |

### Paths on the printer

| Path | Content |
| --- | --- |
| `/mnt/UDISK/.k2openhost/overlay/` | Slot B's writable layer. |
| `/mnt/UDISK/.k2openhost/k2openhost.conf` | `HOST_IP`, `MOONRAKER_URL`, HelixScreen archive. |
| `/mnt/UDISK/.k2openhost/setup.log` | First-boot setup log. |
| `/mnt/UDISK/.k2openhost/backup/<date>/` | U-Boot environment and previous slot B. |
| `/mnt/UDISK/.k2openhost/mcu-fw/<version>/` | Downloaded firmware sets. |
| `/mnt/UDISK/.k2openhost/bin/k2oh-slot` | Slot switch, usable from slot A. |

### Building by hand

```bash
python3 fetch-stock-ota.py --list                 # releases in Creality's index
python3 fetch-stock-ota.py 1.1.0.94 stock         # or "latest"
./build-slot-b.sh --kernel stock/kernel --rootfs stock/rootfs --base-version 1.1.0.94 --out out
```

`build-slot-b.sh` needs `fakeroot` and `squashfs-tools`. `apt-get download squashfs-tools && dpkg -x squashfs-tools_*.deb tools`, then `--tools tools/usr/bin`, works without root.

### What was tested

| Test | Result |
| --- | --- |
| Slot B file list vs stock squashfs | only the intended changes; all other files identical, permissions included |
| Stock OTA download from Creality's CDN | 1.1.0.94 kernel/rootfs MD5 identical to the validated base |
| Newer release 1.1.7.0 | boot scripts slot B changes identical to 1.1.0.94, same services, kernel 5.4.61 with gadget serial and OTG manager; slot B builds with the "not tested" warning. Not booted. |
| Scripts with the printer's own BusyBox and Python 3.9 (chroot) | syntax checks pass |
| Bridge with pseudo-terminals | 10 KB binary both ways, 0 CPU idle, clean stop |
| `k2oh-mcu-fw` extraction vs `unsquashfs` | 15 firmware files byte-identical |
| `k2oh-mcu-fw list/download/stage/unstage/status` | 1.1.7.0 downloaded from Creality, staged and restored |
| `apply` safety check | refused while the host Klipper was ready |
| CFS plan with simulated units | exact variant chosen, up-to-date, invalid and unknown units skipped |
| `k2oh-setup` with the real HelixScreen installer (chroot) | HelixScreen installed, Moonraker host set; service start needs the real system |
| Model check (K2 Pro `F012`, board `CR0CN200400C10`) | read from the reference printer, read-only |
| Writing slot B, trial boot, flashing | **not run on hardware yet** |
