"""update-slot-b.sh on a plain directory: check, update, rerun, revert.

The "image" (K2OH_ROM) is an older slot B: an older k2oh-setup and the 0.1.0
boot links (S56k2oh-bridge, S13mcu_update, no S54k2oh-mcu). The running
system (K2OH_ROOT) starts as a copy of it.
"""

import os
import pathlib
import shutil
import subprocess
import tarfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_SETUP = b"#!/usr/bin/python3\n# old k2oh-setup\n"


def make_image(path):
    shutil.copytree(ROOT / "rootfs", path, ignore=shutil.ignore_patterns("__pycache__"))
    (path / "usr/sbin/k2oh-setup").write_bytes(OLD_SETUP)
    (path / "usr/sbin/k2oh-slot").write_text("#!/bin/sh\n# old k2oh-slot\n")
    (path / "etc").mkdir(exist_ok=True)
    (path / "etc/k2openhost-release").write_text("version=0.1.0\nbase_version=1.1.0.94\n")
    (path / "etc/init.d/mcu_update").write_text("#!/bin/sh /etc/rc.common\n")
    rcd = path / "etc/rc.d"
    rcd.mkdir()
    for link, name in (("S56k2oh-bridge", "k2oh-bridge"), ("K10k2oh-bridge", "k2oh-bridge"),
                       ("S13mcu_update", "mcu_update"), ("S57k2oh-ctl", "k2oh-ctl")):
        os.symlink("../init.d/" + name, rcd / link)


@pytest.fixture
def env(tmp_path):
    bundle = tmp_path / "bundle"
    subprocess.run(["bash", str(ROOT / "make-update-bundle.sh"), "--out", str(bundle)],
                   check=True, capture_output=True)
    rom, root, k2oh = tmp_path / "rom", tmp_path / "root", tmp_path / "k2oh"
    make_image(rom)
    shutil.copytree(rom, root, symlinks=True)
    (k2oh / "bin").mkdir(parents=True)
    run_env = dict(os.environ, K2OH_ROOT=str(root), K2OH_ROM=str(rom), K2OH_DIR=str(k2oh),
                   K2OH_REBOOT_MARK=str(tmp_path / "reboot"))

    def run(*args, check=True):
        result = subprocess.run(["sh", str(bundle / "update-slot-b.sh"), *args],
                                env=run_env, capture_output=True, text=True)
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    return {"bundle": bundle, "rom": rom, "root": root, "k2oh": k2oh, "run": run,
            "reboot": tmp_path / "reboot"}


def links(root):
    rcd = root / "etc/rc.d"
    return {p.name: os.readlink(p) for p in rcd.iterdir() if p.is_symlink()}


def test_check_lists_changes_and_writes_nothing(env):
    before = links(env["root"])
    out = env["run"]("--check").stdout
    assert "/usr/sbin/k2oh-setup" in out
    assert "/etc/rc.d/S54k2oh-mcu -> ../init.d/k2oh-mcu" in out
    assert "S56k2oh-bridge removed" in out and "S13mcu_update removed" in out
    assert "next reboot" in out
    assert (env["root"] / "usr/sbin/k2oh-setup").read_bytes() == OLD_SETUP
    assert links(env["root"]) == before
    assert not (env["root"] / "etc/k2openhost-programs").exists()


def test_update_installs_programs_and_links(env):
    env["run"]()
    root = env["root"]
    assert (root / "usr/sbin/k2oh-setup").read_bytes() == (ROOT / "rootfs/usr/sbin/k2oh-setup").read_bytes()
    assert os.access(root / "usr/sbin/k2oh-setup", os.X_OK)
    current = links(root)
    assert current["S54k2oh-mcu"] == "../init.d/k2oh-mcu"
    assert "S56k2oh-bridge" not in current and "S13mcu_update" not in current
    assert current["K10k2oh-bridge"] == "../init.d/k2oh-bridge"
    stamp = (root / "etc/k2openhost-programs").read_text()
    assert "version=" + (ROOT / "VERSION").read_text().strip() in stamp
    assert "image_version=0.1.0" in stamp
    listed = (env["k2oh"] / "programs-update.list").read_text().split()
    assert "usr/sbin/k2oh-setup" in listed and "etc/rc.d/S54k2oh-mcu" in listed
    backups = list((env["k2oh"] / "backup").iterdir())
    assert (backups[0] / "usr/sbin/k2oh-setup").read_bytes() == OLD_SETUP
    assert env["reboot"].exists()
    # k2oh-slot is kept on UDISK for slot A as well
    assert (env["k2oh"] / "bin/k2oh-slot").read_bytes() == (ROOT / "rootfs/usr/sbin/k2oh-slot").read_bytes()


def test_second_run_has_nothing_to_do(env):
    env["run"]()
    out = env["run"]().stdout
    assert "none: slot B already runs these programs" in out
    assert not env["reboot"].exists()


def test_revert_returns_to_the_image(env):
    env["run"]()
    env["run"]("--revert")
    root = env["root"]
    assert (root / "usr/sbin/k2oh-setup").read_bytes() == OLD_SETUP
    assert links(root) == links(env["rom"])
    assert not (root / "etc/k2openhost-programs").exists()
    assert not (env["k2oh"] / "programs-update.list").exists()
    assert "No update to revert" in env["run"]("--revert").stdout


def test_a_foreign_file_in_the_bundle_is_refused(env):
    bundle = env["bundle"]
    with tarfile.open(bundle / "rootfs.tar", "a") as tar:
        extra = env["root"].parent / "passwd"
        extra.write_text("root::0:0::/root:/bin/sh\n")
        tar.add(extra, arcname="etc/passwd")
    subprocess.run("sha256sum rootfs.tar rootfs-services.txt VERSION update-slot-b.sh > SHA256SUMS",
                   shell=True, cwd=bundle, check=True)
    result = env["run"](check=False)
    assert result.returncode != 0
    assert "etc/passwd" in result.stderr
    assert (env["root"] / "usr/sbin/k2oh-setup").read_bytes() == OLD_SETUP


def test_a_changed_preinit_needs_a_reinstall(env):
    (env["rom"] / "lib/preinit/80_mount_root").write_text("# older overlay mount\n")
    out = env["run"]("--check").stdout
    assert "needs a reinstall" in out and "lib/preinit/80_mount_root" in out


def test_a_bad_checksum_stops_everything(env):
    with open(env["bundle"] / "VERSION", "a") as f:
        f.write("tampered\n")
    result = env["run"](check=False)
    assert result.returncode != 0 and "checksum" in result.stderr
    assert (env["root"] / "usr/sbin/k2oh-setup").read_bytes() == OLD_SETUP
