#!/usr/bin/env bash
# Build the K2-OpenHost slot B image for the Creality K2 Pro T113.
#
# Input: the "kernel" and "rootfs" files of the stock Creality OTA image that
# slot A runs (unpacked from the .img, a cpio archive), by default 1.1.0.94.
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
#   ./build-slot-b.sh --kernel kernel --rootfs rootfs --out out
#   (--tools DIR: directory holding unsquashfs/mksquashfs)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(cat "$HERE/VERSION")"
ROOTFS_PART_BYTES=314572800   # rootfsB, 300 MiB
BOOT_PART_BYTES=16777216      # bootB, 16 MiB

# Stock images this build is validated against (OTA 1.1.0.94, cpio_item_md5).
KNOWN_KERNEL_MD5="42ced67cb382d6919737a15aab658ff6"
KNOWN_ROOTFS_MD5="ea8da1a09c56eb33175822f840cb7fa2"

# Init scripts disabled in slot B (their /etc/rc.d links are removed).
# wipe_data is the factory reset: it deletes most of UDISK, which slot A uses.
DISABLED_SERVICES="klipper klipper_mcu moonraker nginx app adbd webrtc wipe_data S99swupdate_autorun"

kernel="" rootfs="" out="" tools="" allow_other=0
while [ $# -gt 0 ]; do
	case "$1" in
	--kernel) kernel="$2"; shift 2 ;;
	--rootfs) rootfs="$2"; shift 2 ;;
	--out) out="$2"; shift 2 ;;
	--tools) tools="$2"; shift 2 ;;
	--allow-other-base) allow_other=1; shift ;;
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
if [ "$kernel_md5" != "$KNOWN_KERNEL_MD5" ] || [ "$rootfs_md5" != "$KNOWN_ROOTFS_MD5" ]; then
	echo "These are not the stock 1.1.0.94 images this build was validated with." >&2
	echo "  kernel md5 $kernel_md5, rootfs md5 $rootfs_md5" >&2
	[ "$allow_other" = 1 ] || { echo "Use --allow-other-base to build anyway." >&2; exit 1; }
fi

mkdir -p "$out"
work="$(mktemp -d "${TMPDIR:-/tmp}/k2oh-slotb.XXXXXX")"
trap 'rm -rf "$work"' EXIT
state="$work/fakeroot.state"
root="$work/root"

say "Unpacking the stock rootfs"
fakeroot -s "$state" unsquashfs -q -no-progress -d "$root" "$rootfs" >/dev/null

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
release="$(printf 'version=%s\nbuilt=%s\nbase_kernel_md5=%s\nbase_rootfs_md5=%s' \
	"$VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$kernel_md5" "$rootfs_md5")"
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
