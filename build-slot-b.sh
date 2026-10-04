#!/usr/bin/env bash
# Build the K2-OpenHost slot B image for the Creality K2 Pro T113.
#
# Input: the "kernel" and "rootfs" files of a stock Creality K2 Pro OTA image
# (unpacked from the .img, a cpio archive; fetch-stock-ota.py does it).
# Prepared and tested on 1.1.0.94. Newer releases build when the files the
# changes depend on are unchanged (checked below), but booting slot B and
# the T113 USB gadget (OTG) mode are not guaranteed on them.
# Output (in --out): bootB.img, rootfsB.squashfs, SHA256SUMS, manifest.txt,
# k2oh-slot and install-slot-b.sh: copy that directory to the printer.
#
# The kernel is copied unchanged: the stock kernel already has the USB gadget
# drivers. The rootfs is the stock squashfs with the K2-OpenHost changes:
#   - writable layer on UDISK (/mnt/UDISK/.k2openhost/overlay), not on
#     rootfs_data, which stays slot A's;
#   - USB gadget with three serial functions and one bridge per K2 bus;
#   - Creality Klipper, Moonraker, nginx, UI/cloud apps, ADB, WebRTC camera and
#     USB-stick OTA disabled (an OTA started from slot B would overwrite A).
#
# Needs: bash, fakeroot, unsquashfs and mksquashfs (squashfs-tools), sha256sum.
#   ./build-slot-b.sh --kernel kernel --rootfs rootfs --out out [--base-version V]
#   (--tools DIR: directory holding unsquashfs/mksquashfs;
#    --force-preinit: build even if the stock preinit scripts changed)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(cat "$HERE/VERSION")"
ROOTFS_PART_BYTES=314572800   # rootfsB, 300 MiB
BOOT_PART_BYTES=16777216      # bootB, 16 MiB

# Stock releases the work was prepared and tested on (kernel/rootfs MD5 from
# the OTA's cpio_item_md5). Other releases build with a warning.
TESTED_BASES="1.1.0.94:42ced67cb382d6919737a15aab658ff6:ea8da1a09c56eb33175822f840cb7fa2"

# Slot B replaces 80_mount_root and trims 79_format_partition. Both are
# identical in 1.1.0.94 and 1.1.7.0; a release that changes them needs a
# review before slot B can be built from it.
PREINIT_SHA256="01f37a5623b907a549af30a087927f9135442e461639caf43740dbdab72dbc9b  lib/preinit/80_mount_root
56a5345e53f16a89f8be93747c2812d0bed1755decd21b7c53e5c3dc37482b98  lib/preinit/79_format_partition"

# Init scripts disabled in slot B (their /etc/rc.d links are removed).
# wipe_data is the factory reset: it deletes most of UDISK, which slot A uses.
DISABLED_SERVICES="klipper klipper_mcu moonraker nginx app adbd webrtc wipe_data S99swupdate_autorun"

kernel="" rootfs="" out="" tools="" base_version="" force_preinit=0
while [ $# -gt 0 ]; do
	case "$1" in
	--kernel) kernel="$2"; shift 2 ;;
	--rootfs) rootfs="$2"; shift 2 ;;
	--out) out="$2"; shift 2 ;;
	--tools) tools="$2"; shift 2 ;;
	--base-version) base_version="$2"; shift 2 ;;
	--force-preinit) force_preinit=1; shift ;;
	--allow-other-base) shift ;;   # accepted for compatibility; other bases only warn now
	-h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
	*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done
[ -n "$kernel" ] && [ -n "$rootfs" ] && [ -n "$out" ] || { sed -n '2,/^$/p' "$0"; exit 2; }
[ -n "$tools" ] && PATH="$tools:$PATH"
for tool in fakeroot unsquashfs mksquashfs sha256sum md5sum; do
	command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

say() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }

say "Checking the stock images"
[ "$(head -c 8 "$kernel")" = "ANDROID!" ] || { echo "$kernel is not an Android boot image" >&2; exit 1; }
[ "$(head -c 4 "$rootfs")" = "hsqs" ] || { echo "$rootfs is not a squashfs image" >&2; exit 1; }
kernel_md5="$(md5sum "$kernel" | cut -d' ' -f1)"
rootfs_md5="$(md5sum "$rootfs" | cut -d' ' -f1)"
tested=""
for entry in $TESTED_BASES; do
	[ "${entry#*:}" = "$kernel_md5:$rootfs_md5" ] && tested="${entry%%:*}"
done
if [ -n "$tested" ]; then
	echo "stock $tested: the release this work was prepared and tested on"
	base_version="${base_version:-$tested}"
else
	{
		printf '\033[1;33mWARNING: stock %s is not the release this work was tested on (1.1.0.94).\n' "${base_version:-release}"
		printf 'Slot B is built only if the files it changes are identical, but booting it and the\n'
		printf 'T113 USB gadget (OTG) mode are NOT guaranteed on this firmware.\033[0m\n'
	} >&2
fi

mkdir -p "$out"
work="$(mktemp -d "${TMPDIR:-/tmp}/k2oh-slotb.XXXXXX")"
trap 'rm -rf "$work"' EXIT
state="$work/fakeroot.state"
root="$work/root"

say "Unpacking the stock rootfs"
fakeroot -s "$state" unsquashfs -q -no-progress -d "$root" "$rootfs" >/dev/null

say "Checking the stock boot scripts slot B changes"
if ! (cd "$root" && printf '%s\n' "$PREINIT_SHA256" | sha256sum -c --quiet - >/dev/null 2>&1); then
	echo "The stock preinit scripts differ from the reviewed ones (80_mount_root, 79_format_partition)." >&2
	echo "Slot B replaces them, so building from this release needs a review first." >&2
	[ "$force_preinit" = 1 ] || exit 1
	echo "--force-preinit given: building anyway" >&2
fi

say "Applying the K2-OpenHost changes"
cat > "$work/apply.sh" <<'APPLY'
set -euo pipefail
root="$1" src="$2" disabled="$3" release="$4"
(cd "$src" && tar -cf - --exclude=__pycache__ --exclude='*.pyc' .) | (cd "$root" && tar -xf -)
(cd "$src" && find . -name __pycache__ -prune -o -type f ! -name '*.pyc' -print) | while read -r f; do
	chown 0:0 "$root/$f"
	case "$f" in
	./etc/init.d/*|./usr/bin/*|./usr/sbin/*) chmod 0755 "$root/$f" ;;
	*) chmod 0644 "$root/$f" ;;
	esac
done
for svc in $disabled; do
	rm -f "$root"/etc/rc.d/[SK][0-9][0-9]"${svc#S99}"
done
# Wi-Fi after network (S20), gadget and bridges after mcu_update (S13) and
# board_init (S20), first-boot setup last.
ln -sf ../init.d/k2oh-wifi "$root/etc/rc.d/S22k2oh-wifi"
ln -sf ../init.d/k2oh-wifi "$root/etc/rc.d/K89k2oh-wifi"
ln -sf ../init.d/k2oh-gadget "$root/etc/rc.d/S55k2oh-gadget"
ln -sf ../init.d/k2oh-gadget "$root/etc/rc.d/K11k2oh-gadget"
ln -sf ../init.d/k2oh-bridge "$root/etc/rc.d/S56k2oh-bridge"
ln -sf ../init.d/k2oh-bridge "$root/etc/rc.d/K10k2oh-bridge"
ln -sf ../init.d/k2oh-ctl "$root/etc/rc.d/S57k2oh-ctl"
ln -sf ../init.d/k2oh-ctl "$root/etc/rc.d/K09k2oh-ctl"
ln -sf ../init.d/k2oh-firstboot "$root/etc/rc.d/S99k2oh-firstboot"
# rootfs_data belongs to slot A: do not let block-mount attach it to /overlay.
# block-mount must not run e2fsck on UDISK either.
awk -v q="'" '
	/option[ \t]+check_fs/ { sub(/.1.[ \t]*$/, q "0" q) }
	/^config/ { ov = 0 }
	/option[ \t]+target[ \t]+.\/overlay./ { ov = 1 }
	ov && /option[ \t]+enabled/ { sub(/.1.[ \t]*$/, q "0" q) }
	{ print }
' "$root/etc/config/fstab" > "$root/etc/config/fstab.k2oh"
cat "$root/etc/config/fstab.k2oh" > "$root/etc/config/fstab"
rm "$root/etc/config/fstab.k2oh"
# Stock preinit formats UDISK and rootfs_data when they do not look like ext4
# and zeroes the partitions listed in the parts_clean U-Boot variable. Slot B
# shares both with slot A, so it only creates the /dev/by-name links.
sed -i -e '/^[[:space:]]*clean_parts$/d' -e '/^[[:space:]].*do_check_format \/dev\/by-name\//d' \
	"$root/lib/preinit/79_format_partition"
chmod 0755 "$root/etc/dropbear"
printf '%s\n' "$release" > "$root/etc/k2openhost-release"
APPLY
release="$(printf 'version=%s\nbuilt=%s\nbase_version=%s\nbase_tested=%s\nbase_kernel_md5=%s\nbase_rootfs_md5=%s' \
	"$VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${base_version:-unknown}" \
	"$([ -n "$tested" ] && echo yes || echo no)" "$kernel_md5" "$rootfs_md5")"
fakeroot -i "$state" -s "$state" bash "$work/apply.sh" "$root" "$HERE/rootfs" "$DISABLED_SERVICES" "$release"

say "Checking the result"
for svc in klipper klipper_mcu moonraker nginx app adbd webrtc wipe_data swupdate_autorun; do
	if ls "$root"/etc/rc.d/ | grep -qx "[SK][0-9][0-9]$svc"; then
		echo "service $svc is still enabled" >&2; exit 1
	fi
done
for bin in usr/sbin/wpa_supplicant sbin/udhcpc usr/bin/python3 usr/bin/mcu_util usr/bin/mcu_util_485 usr/bin/mcu_reset.sh; do
	[ -e "$root/$bin" ] || [ -L "$root/$bin" ] || { echo "the stock rootfs has no /$bin" >&2; exit 1; }
done
grep -A4 "target.*'/overlay'" "$root/etc/config/fstab" | grep -q "enabled.*'0'" \
	|| { echo "the rootfs_data overlay is still enabled in /etc/config/fstab" >&2; exit 1; }
grep -q "option[[:space:]]*check_fs[[:space:]]*'0'" "$root/etc/config/fstab" \
	|| { echo "block-mount still checks filesystems" >&2; exit 1; }
body="$(sed -n '/^do_format_filesystem()/,/^}/p' "$root/lib/preinit/79_format_partition" | grep -v '^[[:space:]]*$')"
[ "$body" = "$(printf 'do_format_filesystem()\n{\n\tlink_by_name\n}')" ] \
	|| { echo "79_format_partition still formats or cleans partitions:" >&2; echo "$body" >&2; exit 1; }

say "Building rootfsB.squashfs"
rm -f "$out/rootfsB.squashfs"
fakeroot -i "$state" mksquashfs "$root" "$out/rootfsB.squashfs" \
	-comp gzip -b 262144 -noappend -all-root -no-progress -quiet
size="$(stat -c %s "$out/rootfsB.squashfs")"
[ "$size" -lt "$ROOTFS_PART_BYTES" ] || { echo "rootfsB.squashfs ($size bytes) does not fit rootfsB" >&2; exit 1; }

cp "$kernel" "$out/bootB.img"
[ "$(stat -c %s "$out/bootB.img")" -le "$BOOT_PART_BYTES" ] || { echo "bootB.img does not fit bootB" >&2; exit 1; }

install -m 0755 "$HERE/rootfs/usr/sbin/k2oh-slot" "$out/k2oh-slot"
install -m 0755 "$HERE/install-slot-b.sh" "$out/install-slot-b.sh"
(cd "$out" && sha256sum bootB.img rootfsB.squashfs > SHA256SUMS)
{
	echo "K2-OpenHost slot B $VERSION"
	echo "$release"
	echo "disabled services: $DISABLED_SERVICES"
	echo "rootfsB.squashfs: $size bytes"
	cat "$out/SHA256SUMS"
} > "$out/manifest.txt"
say "Done: $out"
cat "$out/manifest.txt"
