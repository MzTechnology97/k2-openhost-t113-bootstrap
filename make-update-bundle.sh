#!/usr/bin/env bash
# Build the bundle update-slot-b.sh installs on a running slot B: K2-OpenHost's
# own programs from rootfs/, the boot links, this checkout's VERSION.
#
#   ./make-update-bundle.sh --out DIR
#
# DIR gets update-slot-b.sh, rootfs.tar, rootfs-services.txt, VERSION and
# SHA256SUMS. rootfs.tar carries only /etc/init.d/k2oh-*, /usr/bin/k2oh-*,
# /usr/sbin/k2oh-*, /usr/bin/chamber_cam_power.sh and lib/preinit/80_mount_root
# (compared on the printer, never installed: it needs a reinstall).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out=""
while [ $# -gt 0 ]; do
	case "$1" in
	--out) out="$2"; shift 2 ;;
	*) echo "usage: $0 --out DIR" >&2; exit 2 ;;
	esac
done
[ -n "$out" ] || { echo "usage: $0 --out DIR" >&2; exit 2; }

rm -rf "$out"
mkdir -p "$out"
list=()
while IFS= read -r path; do
	list+=("$path")
done < <(cd "$HERE/rootfs" && find etc/init.d usr/bin usr/sbin lib/preinit -type f \
	\( -name 'k2oh-*' -o -name chamber_cam_power.sh -o -name 80_mount_root \) \
	! -path '*__pycache__*' ! -name '*.pyc' | sort)
[ "${#list[@]}" -gt 0 ] || { echo "no programs found in $HERE/rootfs" >&2; exit 1; }
tar -C "$HERE/rootfs" --owner=0 --group=0 --mode='u+rwX,go+rX,go-w' -cf "$out/rootfs.tar" "${list[@]}"
cp "$HERE/update-slot-b.sh" "$HERE/rootfs-services.txt" "$HERE/VERSION" "$out/"
(cd "$out" && sha256sum rootfs.tar rootfs-services.txt VERSION update-slot-b.sh > SHA256SUMS)
echo "update bundle $(cat "$HERE/VERSION"): ${#list[@]} files in $out"
