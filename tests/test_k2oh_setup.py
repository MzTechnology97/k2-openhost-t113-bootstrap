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


def fake_proc(tmp_path, processes):
    proc = tmp_path / "proc"
    proc.mkdir()
    for pid, argv in processes.items():
        (proc / str(pid)).mkdir()
        (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (proc / "self").mkdir()
    return proc


def test_helix_pids_finds_launcher_watchdog_ui_and_splash(tmp_path):
    proc = fake_proc(tmp_path, {
        10: ["/bin/sh", "/opt/helixscreen/bin/helix-launcher.sh"],
        11: ["/bin/sh", "/opt/helixscreen/bin/helix-launcher.sh"],
        12: ["/opt/helixscreen/bin/helix-watchdog", "--splash-pid=9", "--", "/opt/helixscreen/bin/helix-screen"],
        13: ["/opt/helixscreen/bin/helix-screen", "--rotate=270"],
        14: ["/opt/helixscreen/bin/helix-splash"],
        20: ["/opt/helixscreen/bin/ustreamer", "--device", "/dev/video0"],
        21: ["/bin/sh", "/etc/init.d/S99helixscreen", "restart"],
        22: ["tail", "-f", "/opt/helixscreen/bin/helix-screen"],
    })
    assert sorted(setup.helix_pids(str(proc))) == [10, 11, 12, 13, 14]


def test_restart_helix_stops_leftovers_before_start(tmp_path, monkeypatch):
    proc = fake_proc(tmp_path, {
        10: ["/bin/sh", "/opt/helixscreen/bin/helix-launcher.sh"],
        12: ["/opt/helixscreen/bin/helix-watchdog"],
    })
    events = []
    monkeypatch.setattr(setup, "HELIX_INIT", "/etc/init.d/S99helixscreen")
    monkeypatch.setattr(setup.subprocess, "run", lambda argv, **kw: events.append(argv[1]))

    def kill(pid, sig):
        events.append(("kill", pid, sig))
        (proc / str(pid) / "cmdline").unlink()
        (proc / str(pid)).rmdir()

    monkeypatch.setattr(setup.os, "kill", kill)
    monkeypatch.setattr(setup.time, "sleep", lambda s: None)
    setup.restart_helix(str(proc))
    assert events[0] == "stop"
    assert events[-1] == "start"
    killed = sorted(e[1] for e in events if isinstance(e, tuple))
    assert killed == [10, 12]
    assert all(e[2] == setup.signal.SIGTERM for e in events if isinstance(e, tuple))
