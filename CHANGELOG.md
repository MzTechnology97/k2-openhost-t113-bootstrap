# Changelog

## Unreleased

- Moved into its own repository from `k2-openhost-installer-helper` (`t113/slot-b`), history kept. The installer helper clones it.
- Slot B can be built from Creality releases newer than 1.1.0.94. You get a warning and a confirmation: the bootstrap and the T113 USB gadget (OTG) mode are not guaranteed on them. The build refuses when the stock boot scripts it changes differ from the reviewed ones (identical in 1.1.0.94 and 1.1.7.0).
- `k2oh-mcu-fw update`: downloads the latest Creality release, stages it, shows the changes and flashes only on confirmation.
- `k2oh-mcu-fw apply --cfs`: flashes the CFS through the recovered `cfs_update.json` format, using the exact hardware variant reported by Creality's updater.
- First-boot `k2oh-setup` (HelixScreen pointed at the external host), Wi-Fi without Creality's wifi-server.
- Strict K2 Pro checks: model `F012`, board `CR0CN200400C10`.
- Slot B never formats, checks or wipes UDISK or slot A's `rootfs_data`.
- `k2oh-mcu-fw apply` refuses to flash unless Moonraker on the host reports Klippy `disconnected` and a fresh proof from the host (`host/k2oh-host-evidence`, `--host-evidence`) shows the Klipper service stopped and this printer's three gadget ports free. Unknown, unreachable, timeout and malformed answers block; `--yes` no longer skips any check; `--host-stopped` is gone. Every step's exit code is checked, the bridges are always restarted and a failed restart is an error ([#1](https://github.com/MzTechnology97/k2-openhost-t113-bootstrap/issues/1)).

Status: built and tested offline, prepared on firmware 1.1.0.94; not yet booted on a printer.
