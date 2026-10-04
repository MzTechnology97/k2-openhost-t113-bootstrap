#!/bin/sh
# Write the K2-OpenHost system to slot B of a Creality K2 Pro, from slot A.
#
# Run as root on the printer, in the directory build-slot-b.sh produced
# (bootB.img, rootfsB.squashfs, SHA256SUMS, k2oh-slot, this script):
#
#   sh install-slot-b.sh            check everything, write slot B, verify it
#   sh install-slot-b.sh --check    checks only, writes nothing
#
# Slot A (bootA, rootfsA, rootfs_data) is never written. The previous slot B
# content and the U-Boot environment are saved to /mnt/UDISK/.k2openhost/backup.
# This script does not change which slot boots: run 'k2oh-slot boot-b' and
# reboot when you are ready (a power cycle then returns to slot A if slot B
# does not come up).

set -e

K2OH_DIR=/mnt/UDISK/.k2openhost
STOCK_VERSION="1.1.0.94"
STOCK_KERNEL="#5 SMP PREEMPT Fri Sep 26 16:07:42 CST 2025"
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECK_ONLY=0
[ "$1" = "--check" ] && CHECK_ONLY=1

say() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mk2oh: %s\033[0m\n' "$*" >&2; exit 1; }

part_bytes() { echo $(( $(cat "/sys/class/block/$(basename "$(readlink -f "$1")")/size") * 512 )); }

say "Checking the printer"
[ "$(id -u)" = "0" ] || die "run as root"
case " $(cat /proc/cmdline) " in
*" root=/dev/mmcblk0p6 "*) ;;
*) die "this must run from slot A (root=/dev/mmcblk0p6)" ;;
esac
mkdir -p /var/lock
[ "$(fw_printenv -n boot_partition)/$(fw_printenv -n root_partition)" = "bootA/rootfsA" ] \
	|| die "the U-Boot environment does not point at slot A"
grep -q "\"sys_version\":\"$STOCK_VERSION\"" /mnt/UDISK/creality/userdata/config/system_version.json 2>/dev/null \
	|| die "slot A is not the stock $STOCK_VERSION firmware this image is built from"
case "$(uname -v)" in
"$STOCK_KERNEL") ;;
*) die "the running kernel is not the stock $STOCK_VERSION kernel ($(uname -v))" ;;
esac
grep -q " /mnt/UDISK " /proc/mounts || die "/mnt/UDISK is not mounted"
for dev in bootB rootfsB env env-redund; do
	[ -e "/dev/by-name/$dev" ] || die "missing /dev/by-name/$dev"
done

say "Checking the images"
cd "$HERE"
for f in bootB.img rootfsB.squashfs SHA256SUMS k2oh-slot; do
	[ -f "$f" ] || die "missing $f in $HERE"
done
sha256sum -c SHA256SUMS || die "checksum mismatch"
[ "$(head -c 8 bootB.img)" = "ANDROID!" ] || die "bootB.img is not a boot image"
[ "$(head -c 4 rootfsB.squashfs)" = "hsqs" ] || die "rootfsB.squashfs is not a squashfs image"
boot_size=$(wc -c < bootB.img)
rootfs_size=$(wc -c < rootfsB.squashfs)
[ "$boot_size" -le "$(part_bytes /dev/by-name/bootB)" ] || die "bootB.img does not fit bootB"
[ "$rootfs_size" -le "$(part_bytes /dev/by-name/rootfsB)" ] || die "rootfsB.squashfs does not fit rootfsB"
free_kb=$(df -k /mnt/UDISK | awk 'NR==2 {print $4}')
[ "$free_kb" -gt 700000 ] || die "UDISK needs about 700 MB free for the backups"

if [ "$CHECK_ONLY" = 1 ]; then
	say "All checks passed (nothing written)"
	exit 0
fi

stamp=$(date +%Y%m%d-%H%M%S)
backup="$K2OH_DIR/backup/$stamp"
say "Saving the U-Boot environment and the current slot B to $backup"
mkdir -p "$backup"
dd if=/dev/by-name/env of="$backup/env.bin" bs=128k count=1 2>/dev/null
dd if=/dev/by-name/env-redund of="$backup/env-redund.bin" bs=128k count=1 2>/dev/null
dd if=/dev/by-name/bootB of="$backup/bootB.bin" bs=1M 2>/dev/null
dd if=/dev/by-name/rootfsB of="$backup/rootfsB.bin" bs=1M 2>/dev/null
(cd "$backup" && sha256sum *.bin > SHA256SUMS)
sync

say "Writing slot B"
dd if=bootB.img of=/dev/by-name/bootB bs=1M conv=fsync 2>/dev/null
dd if=rootfsB.squashfs of=/dev/by-name/rootfsB bs=1M conv=fsync 2>/dev/null
sync
echo 3 > /proc/sys/vm/drop_caches

say "Verifying slot B"
want_boot=$(sha256sum bootB.img | cut -d' ' -f1)
want_rootfs=$(sha256sum rootfsB.squashfs | cut -d' ' -f1)
got_boot=$(head -c "$boot_size" /dev/by-name/bootB | sha256sum | cut -d' ' -f1)
got_rootfs=$(head -c "$rootfs_size" /dev/by-name/rootfsB | sha256sum | cut -d' ' -f1)
[ "$got_boot" = "$want_boot" ] || die "bootB readback does not match"
[ "$got_rootfs" = "$want_rootfs" ] || die "rootfsB readback does not match"

say "Preparing the slot B writable layer"
upper="$K2OH_DIR/overlay/upper"
mkdir -p "$upper/etc/dropbear" "$K2OH_DIR/overlay/work" "$K2OH_DIR/bin"
chmod 0755 "$upper/etc" "$upper/etc/dropbear"
if [ -s /etc/dropbear/authorized_keys ]; then
	cp /etc/dropbear/authorized_keys "$upper/etc/dropbear/authorized_keys"
	chmod 0600 "$upper/etc/dropbear/authorized_keys"
	echo "  copied slot A's SSH authorized_keys to slot B"
fi
cp "$HERE/k2oh-slot" "$K2OH_DIR/bin/k2oh-slot"
chmod 0755 "$K2OH_DIR/bin/k2oh-slot"
sync

say "Slot B is installed"
echo "Slot A is unchanged and still boots by default."
echo "To try slot B:   $K2OH_DIR/bin/k2oh-slot boot-b && reboot"
echo "If slot B does not come up, power cycle the printer: it returns to slot A."
