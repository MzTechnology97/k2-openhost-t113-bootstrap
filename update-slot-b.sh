#!/bin/sh
# Update K2-OpenHost's own programs on a running slot B, without reinstalling.
#
# Run as root on the printer, in the directory make-update-bundle.sh produced
# (this script, rootfs.tar, rootfs-services.txt, VERSION, SHA256SUMS):
#
#   sh update-slot-b.sh --check            what would change, writes nothing
#   sh update-slot-b.sh                    update
#   sh update-slot-b.sh --revert [--check] back to the installed image's programs
#
# Only K2-OpenHost's programs are updated: /etc/init.d/k2oh-*, /usr/bin/k2oh-*,
# /usr/sbin/k2oh-*, /usr/bin/chamber_cam_power.sh, and the boot links of
# rootfs-services.txt. They land in slot B's writable layer; the read-only
# image underneath is not touched, and a reinstall (install-slot-b.sh) drops
# them. A change anywhere else (kernel, lib/preinit, the Creality base) needs
# a reinstall: --check names it.
#
# The previous versions are saved to /mnt/UDISK/.k2openhost/backup/programs-*.
# When an updated program only runs at boot, the script says a reboot is
# needed and leaves /tmp/k2oh-update-reboot for the installer helper.
#
# Tests run it on a plain directory: K2OH_ROOT (the system root), K2OH_ROM
# (the image) and K2OH_DIR replace /, /rom and /mnt/UDISK/.k2openhost, and the
# printer checks and service restarts are skipped.

set -e

ROOT="${K2OH_ROOT:-}"
ROM="${K2OH_ROM:-/rom}"
K2OH_DIR="${K2OH_DIR:-/mnt/UDISK/.k2openhost}"
K2_PRO_MODEL="F012"
K2_PRO_BOARD="CR0CN200400C10"
HERE="$(cd "$(dirname "$0")" && pwd)"
LIST="$K2OH_DIR/programs-update.list"
STAMP="$ROOT/etc/k2openhost-programs"
REBOOT_MARK="${K2OH_REBOOT_MARK:-/tmp/k2oh-update-reboot}"
CHECK_ONLY=0
REVERT=0
while [ $# -gt 0 ]; do
	case "$1" in
	--check) CHECK_ONLY=1; shift ;;
	--revert) REVERT=1; shift ;;
	*) echo "usage: sh update-slot-b.sh [--revert] [--check]" >&2; exit 2 ;;
	esac
done

say() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mk2oh: %s\033[0m\n' "$*" >&2; exit 1; }
testing() { [ -n "$ROOT" ]; }

# Paths a bundle may carry: K2-OpenHost's programs, and the preinit hook,
# which is only compared (it runs before the writable layer exists).
owned() {
	case "$1" in
	etc/init.d/k2oh-*|usr/bin/k2oh-*|usr/sbin/k2oh-*|usr/bin/chamber_cam_power.sh) return 0 ;;
	esac
	return 1
}

say "Checking the printer"
if ! testing; then
	[ "$(id -u)" = "0" ] || die "run as root"
	case " $(cat /proc/cmdline) " in
	*" root=/dev/mmcblk0p7 "*) ;;
	*) die "this runs on a running slot B; from slot A, reinstall with install-slot-b.sh" ;;
	esac
	[ "$(get_sn_mac.sh model 2>/dev/null)" = "$K2_PRO_MODEL" ] \
		&& [ "$(get_sn_mac.sh board 2>/dev/null)" = "$K2_PRO_BOARD" ] \
		|| die "this is not a Creality K2 Pro (model $K2_PRO_MODEL, board $K2_PRO_BOARD)"
fi
[ -f "$ROOT/etc/k2openhost-release" ] || die "no /etc/k2openhost-release: this is not K2-OpenHost slot B"
image_version=$(sed -n 's/^version=//p' "$ROOT/etc/k2openhost-release")
echo "  slot B image ${image_version:-unknown}"
if [ -f "$STAMP" ]; then echo "  programs updated to $(sed -n 's/^version=//p' "$STAMP")"; fi

rm -f "$REBOOT_MARK"
work=$(mktemp -d /tmp/k2oh-update.XXXXXX)
trap 'rm -rf "$work"' EXIT
reboot=0
changed=""
restart=""
reinstall=""

# A program that runs only at boot takes effect after a reboot; the
# others are restarted now.
note_effect() {
	case "$1" in
	usr/bin/k2oh-ctl|etc/init.d/k2oh-ctl) restart="$restart k2oh-ctl" ;;
	usr/bin/k2oh-bridge|etc/init.d/k2oh-bridge) restart="$restart k2oh-bridge" ;;
	etc/init.d/k2oh-*|usr/sbin/k2oh-mcu-start|usr/bin/chamber_cam_power.sh) reboot=1 ;;
	esac
}

# --- the bundle -------------------------------------------------------------

if [ "$REVERT" = 0 ]; then
	say "Checking the bundle"
	cd "$HERE"
	for f in rootfs.tar rootfs-services.txt VERSION SHA256SUMS; do
		[ -f "$f" ] || die "missing $f in $HERE"
	done
	sha256sum -c SHA256SUMS >/dev/null || die "checksum mismatch in the bundle"
	version=$(cat VERSION)
	tar -xf rootfs.tar -C "$work"
	files=$(cd "$work" && find . -type f | sed 's|^\./||' | sort)
	reinstall=""
	for path in $files; do
		if [ "$path" = "lib/preinit/80_mount_root" ]; then
			cmp -s "$work/$path" "$ROM/$path" || reinstall="$reinstall $path"
			continue
		fi
		owned "$path" || die "the bundle carries $path, which is not a K2-OpenHost program"
		if ! cmp -s "$work/$path" "$ROOT/$path"; then
			changed="$changed $path"
		fi
	done
	echo "  bundle $version"
fi

# --- boot links -------------------------------------------------------------

# Prints "add LINK NAME" and "remove LINK" for the boot links the spec wants.
link_plan() {
	spec="$1"
	while read -r verb first second; do
		case "$verb" in
		disable)
			for entry in "$ROOT"/etc/rc.d/[SK][0-9][0-9]"$first"; do
				[ -e "$entry" ] || [ -L "$entry" ] || continue
				echo "remove $(basename "$entry")"
			done ;;
		link)
			[ "$(readlink "$ROOT/etc/rc.d/$first" 2>/dev/null)" = "../init.d/$second" ] \
				|| echo "add $first $second" ;;
		esac
	done < "$spec"
	wanted=$(awk '$1 == "link" {print $2}' "$spec")
	for entry in "$ROOT"/etc/rc.d/[SK][0-9][0-9]k2oh-*; do
		[ -e "$entry" ] || [ -L "$entry" ] || continue
		name=$(basename "$entry")
		echo "$wanted" | grep -qx "$name" || echo "remove $name"
	done
}

if [ "$REVERT" = 0 ]; then
	links=$(link_plan "$HERE/rootfs-services.txt")
else
	# Back to the image: every path an update wrote takes the image's version.
	[ -f "$LIST" ] || { say "No update to revert: slot B runs its image's programs"; exit 0; }
	links=""
	changed=""
	for path in $(sort -u "$LIST"); do
		case "$path" in
		etc/rc.d/*)
			name=${path#etc/rc.d/}
			if [ -L "$ROM/$path" ]; then
				[ "$(readlink "$ROOT/$path" 2>/dev/null)" = "$(readlink "$ROM/$path")" ] \
					|| links="$links
add $name $(basename "$(readlink "$ROM/$path")")"
			elif [ -e "$ROOT/$path" ] || [ -L "$ROOT/$path" ]; then
				links="$links
remove $name"
			fi ;;
		*)
			if [ -f "$ROM/$path" ]; then
				cmp -s "$ROM/$path" "$ROOT/$path" || changed="$changed $path"
			elif [ -e "$ROOT/$path" ]; then
				changed="$changed $path"
			fi ;;
		esac
	done
	version="image ${image_version:-unknown}"
fi
links=$(echo "$links" | sed '/^$/d')

for path in $changed; do note_effect "$path"; done
if [ -n "$links" ]; then reboot=1; fi

say "Changes"
if [ -z "$changed" ] && [ -z "$links" ]; then
	echo "  none: slot B already runs these programs"
fi
for path in $changed; do echo "  /$path"; done
echo "$links" | while read -r verb first second; do
	case "$verb" in
	add) echo "  boot link /etc/rc.d/$first -> ../init.d/$second" ;;
	remove) echo "  boot link /etc/rc.d/$first removed" ;;
	esac
done
if [ -n "$reinstall" ]; then
	printf '\033[1;33m  needs a reinstall, not applied:%s\033[0m\n' "$reinstall"
fi
if [ "$reboot" = 1 ]; then echo "  takes effect at the next reboot of the printer"; fi
if [ -n "$restart" ]; then echo "  restarts:$(echo "$restart" | tr ' ' '\n' | sort -u | tr '\n' ' ')"; fi

if [ "$CHECK_ONLY" = 1 ] || { [ -z "$changed" ] && [ -z "$links" ]; }; then
	exit 0
fi

# --- apply ------------------------------------------------------------------

stamp=$(date +%Y%m%d-%H%M%S)
backup="$K2OH_DIR/backup/programs-$stamp"
say "Saving the current programs to $backup"
mkdir -p "$backup"
for path in $changed; do
	[ -f "$ROOT/$path" ] || continue
	mkdir -p "$backup/$(dirname "$path")"
	cp -p "$ROOT/$path" "$backup/$path"
done
ls -l "$ROOT/etc/rc.d" > "$backup/rc.d.txt" 2>/dev/null || true

say "Installing"
for path in $changed; do
	target="$ROOT/$path"
	if [ "$REVERT" = 1 ] && [ ! -f "$ROM/$path" ]; then
		rm -f "$target"
		continue
	fi
	source="$work/$path"
	if [ "$REVERT" = 1 ]; then source="$ROM/$path"; fi
	mkdir -p "$(dirname "$target")"
	cp "$source" "$target.k2oh-new"
	chmod 0755 "$target.k2oh-new"
	mv "$target.k2oh-new" "$target"
	if [ "$REVERT" = 0 ]; then echo "$path" >> "$LIST"; fi
done
echo "$links" | while read -r verb first second; do
	case "$verb" in
	add) ln -sf "../init.d/$second" "$ROOT/etc/rc.d/$first" ;;
	remove) rm -f "$ROOT/etc/rc.d/$first" ;;
	*) continue ;;
	esac
	if [ "$REVERT" = 0 ]; then echo "etc/rc.d/$first" >> "$LIST"; fi
done
# k2oh-slot is also kept on UDISK, where slot A finds it.
case " $changed " in
*" usr/sbin/k2oh-slot "*) cp "$ROOT/usr/sbin/k2oh-slot" "$K2OH_DIR/bin/k2oh-slot" 2>/dev/null || true ;;
esac
if [ "$REVERT" = 1 ]; then
	rm -f "$STAMP" "$LIST"
else
	printf 'version=%s\nupdated=%s\nimage_version=%s\n' \
		"$version" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${image_version:-unknown}" > "$STAMP"
fi
sync

if [ -n "$restart" ] && ! testing; then
	for service in $(echo "$restart" | tr ' ' '\n' | sort -u); do
		say "Restarting $service"
		"/etc/init.d/$service" restart || die "$service did not restart"
	done
fi
say "Slot B programs: $version"
if [ "$reboot" = 1 ]; then
	touch "$REBOOT_MARK"
	echo "Reboot the printer for the boot-time changes (installer helper: it asks)."
fi
