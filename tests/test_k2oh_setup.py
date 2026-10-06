"""k2oh-setup: HelixScreen's boot wait polls Moonraker on the external host."""

import importlib.machinery
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader(
        "k2oh_setup", str(ROOT / "rootfs/usr/sbin/k2oh-setup"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


setup = load()

INIT = "#!/bin/sh\n# HelixScreen init\nDAEMON_DIR=/opt/helixscreen\n"


def init_script(tmp_path, monkeypatch, text=INIT):
    path = tmp_path / "S99helixscreen"
    path.write_text(text)
    path.chmod(0o755)
    monkeypatch.setattr(setup, "HELIX_INIT", str(path))
    return path


def test_wait_line_added_after_shebang(tmp_path, monkeypatch):
    path = init_script(tmp_path, monkeypatch)
    assert setup.point_helix_wait("10.10.1.97", "7125")
    lines = path.read_text().split("\n")
    assert lines[0] == "#!/bin/sh"
    assert lines[1].startswith('export HELIX_MOONRAKER_READY_URL="http://10.10.1.97:7125/server/info"')
    assert lines[2:] == INIT.split("\n")[1:]
    assert path.stat().st_mode & 0o777 == 0o755


def test_wait_line_is_idempotent_and_follows_the_host(tmp_path, monkeypatch):
    path = init_script(tmp_path, monkeypatch)
    setup.point_helix_wait("10.10.1.97", "7125")
    assert not setup.point_helix_wait("10.10.1.97", "7125")
    assert setup.point_helix_wait("10.10.1.50", "7125")
    text = path.read_text()
    assert text.count("HELIX_MOONRAKER_READY_URL") == 1
    assert "10.10.1.50:7125" in text


def test_no_init_or_no_shebang_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "HELIX_INIT", str(tmp_path / "missing"))
    assert not setup.point_helix_wait("10.10.1.97", "7125")
    path = init_script(tmp_path, monkeypatch, "echo no shebang\n")
    assert not setup.point_helix_wait("10.10.1.97", "7125")
    assert path.read_text() == "echo no shebang\n"
