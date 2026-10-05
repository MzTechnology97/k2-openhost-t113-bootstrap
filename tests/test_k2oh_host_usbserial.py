import os
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "host" / "k2oh-host-usbserial"


def run_script(tmp_path, command):
    env = os.environ.copy()
    env.update({
        "K2OH_ETC_ROOT": str(tmp_path / "etc"),
        "K2OH_SYS_ROOT": str(tmp_path / "sys"),
        "K2OH_DEV_ROOT": str(tmp_path / "dev"),
        "K2OH_ALLOW_NONROOT": "1",
        "K2OH_SKIP_RUNTIME": "1",
    })
    return subprocess.run(
        ["sh", str(SCRIPT), command],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_install_persists_generic_usbserial_binding(tmp_path):
    result = run_script(tmp_path, "install")
    modprobe = tmp_path / "etc/modprobe.d/k2-openhost-gadget-serial.conf"
    modules = tmp_path / "etc/modules-load.d/k2-openhost-gadget-serial.conf"

    assert "options usbserial vendor=0x0525 product=0xa4a6" in modprobe.read_text()
    assert modules.read_text().splitlines()[-1] == "usbserial"
    assert "ttyUSB channels: 0" in result.stdout


def test_remove_only_removes_persistent_files(tmp_path):
    run_script(tmp_path, "install")
    run_script(tmp_path, "remove")

    assert not (tmp_path / "etc/modprobe.d/k2-openhost-gadget-serial.conf").exists()
    assert not (tmp_path / "etc/modules-load.d/k2-openhost-gadget-serial.conf").exists()


def test_status_does_not_require_root(tmp_path):
    result = run_script(tmp_path, "status")
    assert "0525:a4a6" in result.stdout
    assert "gadget:          not-present" in result.stdout
