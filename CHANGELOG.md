# Changelog

## 0.1.2

Fixes from the first MCU firmware updates on the reference printer (2026-10-06):

- **The CFS is flashed only by `apply --cfs`.** `mcu_util_485` flashes a CFS at every run when `fw/cfs/version.json` lists another version for it, with or without `CFS=1`: a plain `apply` after staging 1.1.7.0 flashed the CFS 113 → 153, and every boot of slot B would have done the same. Slot B now keeps that list empty and the real one in `version.json.k2oh`: the build, `stage`/`unstage`, every `apply` and `k2oh-mcu` at boot put it aside, and only `apply --cfs` puts it back for its own run. A custom image goes only through the `CFS=1` pass. Checked on the printer: with the empty list, motors, RFID and CFS start normally and the CFS is not flashed.
- **Custom CFS images keep the stock file name.** The staged copy was `custom-cfs/<boot>-<sha256>.bin`, and `mcu_util_485` takes the application version it writes to the CFS from the file name: it wrote `3cf3385dcbc5`, and the CFS loader refused to start the application (`start_app NACK`). The copy is now `custom-cfs/<sha256>/<boot>-<app>.bin`. The CFS was recovered with a normal `mcu_update` (stock 153).
- **A reinstall drops old copies of K2-OpenHost's programs from the writable layer** (`/etc/init.d/k2oh-*`, `/usr/bin/k2oh-*`, `/usr/sbin/k2oh-*`, `chamber_cam_power.sh`), so a fix copied by hand before a release never hides the new image's version.

## 0.1.1

Fixes from the first boot of slot B on the reference printer (0.1.0, trial boot, 2026-10-06):

- **The boards start before the bridges.** Stock `mcu_update` no longer has a boot link in slot B. The new `k2oh-mcu` (S54) power-cycles the MCU rail with `mcu_reset.sh`, runs `mcu_update` and only then starts the bridges, which lost their own boot link. On 0.1.0, procd ran `mcu_update` while the bridges already read the same UARTs: the bridges took `mcu_util`'s answers, the handshake failed, the Main and Nozzle MCUs were never started and an X/Y motor stayed in Creality's loader. After the reboot of the T113 alone, the MCU rail had stayed on and the boards kept the previous host session, so Klipper's reset failed ("Failed automated reset of MCU"). `/tmp/k2oh-mcu.ready` holds `mcu_update`'s exit code. procd does not keep the rc.d order either: on the second boot GPIO140 (MCU rail) was not exported yet, because `board_init` (S20) had not run, so `k2oh-mcu` runs `mcu_reset.sh enable` itself before the cycle. When the Main or Nozzle MCU still has no version after `mcu_update`, the cycle and `mcu_update` run once more.
- **Same SSH host keys in both slots.** `install-slot-b.sh` copies slot A's dropbear host keys: on 0.1.0, slot B generated its own and SSH clients reported a changed host key.
- **Short overlay name** (`overlayfs:/overlay`, as in stock). The long one made BusyBox `df` wrap its line, and the HelixScreen installer read 0 MB free on `/` and refused to install.
- **HelixScreen's boot wait polls the host.** `k2oh-setup` sets `HELIX_MOONRAKER_READY_URL` to Moonraker on the external host in HelixScreen's init script (a marked line). It waited 120 s for a local Moonraker that slot B does not run. When it changes HelixScreen's settings, `k2oh-setup` restarts it cleanly (stop, end what the stop leaves, start): at the first boot after the install it restarted HelixScreen while the init script was still starting it, and two watchdogs fought over the screen ("Another instance of helix-screen is already running").
- Docs: slot B's gadget by-id names (`usb-Creality_K2_Pro_K2-OpenHost_Gadget_Serial_<serial>-…`) differ from slot A's stock gadget; the host should use the udev names `/dev/k2-*`.

## 0.1.0

- `k2oh-mcu-fw apply --cfs --cfs-image ... --cfs-sha256 ...`: supports explicitly verified same-version custom CFS images while keeping the actual write on Creality stock `mcu_util_485`, with exact boot/app/UUID matching.

- Moved into its own repository from `k2-openhost-installer-helper` (`t113/slot-b`), history kept. The installer helper clones it.
- Slot B can be built from Creality releases newer than 1.1.0.94. You get a warning and a confirmation: the bootstrap and the T113 USB gadget (OTG) mode are not guaranteed on them. The build refuses when the stock boot scripts it changes differ from the reviewed ones (identical in 1.1.0.94 and 1.1.7.0).
- `k2oh-mcu-fw update`: downloads the latest Creality release, stages it, shows the changes and flashes only on confirmation.
- `k2oh-mcu-fw apply --cfs`: flashes the CFS through the recovered `cfs_update.json` format, using the exact hardware variant reported by Creality's updater.
- First-boot `k2oh-setup` (HelixScreen pointed at the external host), Wi-Fi without Creality's wifi-server.
- Strict K2 Pro checks: model `F012`, board `CR0CN200400C10`.
- Slot B never formats, checks or wipes UDISK or slot A's `rootfs_data`.
- `k2oh-ctl`: control service for the external host (telemetry, MCU power rail GPIO140 with power cycle and e-stop, buzzer GPIO164, bridge and HelixScreen restart, Moonraker `http` power device endpoint). It answers only `HOST_IP` with the token in `ctl.token`, which the install creates. Disruptive actions need an idle print state on the host. Tested from RAM on slot A of the development printer.
- `k2oh-bridge` writes per-channel counters (bytes, last data from host and UART) to `/tmp/k2oh-bridge/` for the telemetry.
- `k2oh-bridge` rewritten from the USB link benchmarks:
  - per-direction non-blocking queues: a stalled side no longer freezes the other, which made the UART overrun;
  - EOF on the gadget port, as after a USB reconnect, reopens it (at most once a second) instead of spinning at 100% CPU on a dead descriptor;
  - waits for missing ports;
  - exits with a reason on a lost port, and procd restarts it after 1 s (`respawn 60 1 0`);
  - counters written in quiet moments only;
  - `BRIDGE_OPTS` in `k2openhost.conf`.
- `k2oh-linkstat`: optional low-cost sampler of the T113 side of the link for long prints.
- `k2oh-mcu-fw apply` refuses to flash unless Moonraker on the host reports Klippy `disconnected` and a fresh proof from the host (`host/k2oh-host-evidence`, `--host-evidence`) shows the Klipper service stopped and this printer's three gadget ports free. Unknown, unreachable, timeout and malformed answers block; `--yes` no longer skips any check; `--host-stopped` is gone. Every step's exit code is checked, the bridges are always restarted and a failed restart is an error ([#1](https://github.com/MzTechnology97/k2-openhost-t113-bootstrap/issues/1)).

Status: built and tested offline, prepared on firmware 1.1.0.94. First booted on the reference printer on 2026-10-06 (trial boot); the fixes are in 0.1.1.