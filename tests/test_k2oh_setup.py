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


def test_helix_camera_server_is_disabled_once(tmp_path, monkeypatch):
    init = tmp_path / "ustreamer"
    init.write_text("#!/bin/sh /etc/rc.common\n")
    rc_dir = tmp_path / "rc.d"
    rc_dir.mkdir()
    (rc_dir / "S95ustreamer").write_text("")
    calls = []

    def run(argv, **kw):
        calls.append(argv[1])
        if argv[1] == "disable":
            (rc_dir / "S95ustreamer").unlink()

    monkeypatch.setattr(setup.subprocess, "run", run)
    assert setup.disable_helix_camera(str(init), str(rc_dir)) is True
    assert calls == ["stop", "disable"]
    # Already disabled, or no camera server installed: nothing to do.
    assert setup.disable_helix_camera(str(init), str(rc_dir)) is False
    assert setup.disable_helix_camera(str(tmp_path / "missing"), str(rc_dir)) is False
    assert calls == ["stop", "disable"]


def helix_tree(tmp_path, monkeypatch, version):
    """A fake /opt/helixscreen and /etc/init.d with HelixScreen's scripts."""
    helix = tmp_path / "opt" / "helixscreen"
    (helix / "config").mkdir(parents=True)
    (helix / "VERSION").write_text(version)
    (helix / "config" / "settings.json").write_text("{}")
    init_d = tmp_path / "init.d"
    init_d.mkdir(exist_ok=True)
    (init_d / "S99helixscreen").write_text("#!/bin/sh\n# %s\n" % version)
    (init_d / "helixscreen").write_text("#!/bin/sh /etc/rc.common\n")
    monkeypatch.setattr(setup, "HELIX_DIR", str(helix))
    monkeypatch.setattr(setup, "HELIX_INIT", str(init_d / "S99helixscreen"))
    monkeypatch.setattr(setup, "HELIX_SERVICE", str(init_d / "helixscreen"))
    monkeypatch.setattr(setup, "K2OH_DIR", str(tmp_path / "k2oh"))
    monkeypatch.setattr(setup, "HELIX_BACKUPS", str(tmp_path / "k2oh" / "helix-backup"))
    return helix, init_d


def release_archive(tmp_path):
    import io
    import tarfile
    path = tmp_path / "helixscreen-k2-v1.0.6.tar.gz"
    data = b"#!/bin/sh\necho installer\n"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("helixscreen/install.sh")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return path


class Result:
    def __init__(self, returncode=0):
        self.returncode = returncode


CONF = {"HOST_IP": "10.10.1.97", "MOONRAKER_PORT": "7125"}


def test_helix_update_refuses_unless_idle(tmp_path, monkeypatch):
    helix_tree(tmp_path, monkeypatch, "old")
    archive = release_archive(tmp_path)
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: 1 / 0)
    for state in ("printing", "paused", "unreachable"):
        monkeypatch.setattr(setup, "print_state", lambda conf, s=state: s)
        assert setup.update_helix(CONF, str(archive)) == 1
        assert setup.restore_helix(CONF) == 1
    assert not (tmp_path / "k2oh" / "helix-backup").exists()


def test_helix_update_saves_runs_the_release_installer_and_repoints(tmp_path, monkeypatch):
    helix, init_d = helix_tree(tmp_path, monkeypatch, "old")
    archive = release_archive(tmp_path)
    monkeypatch.setattr(setup, "print_state", lambda conf: "standby")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        assert pathlib.Path(argv[1]).read_text() == "#!/bin/sh\necho installer\n"
        return Result(0)

    monkeypatch.setattr(setup.subprocess, "run", run)
    monkeypatch.setattr(setup, "point_helix", lambda host, port: calls.append(["point", host, port]))
    monkeypatch.setattr(setup, "disable_helix_camera", lambda: calls.append(["camera"]))
    assert setup.update_helix(CONF, str(archive)) == 0
    assert calls[0][2:] == ["--update", "--local", str(archive), "--skip-kiauh-registration"]
    assert calls[1:] == [["point", "10.10.1.97", "7125"], ["camera"]]
    (backup,) = (tmp_path / "k2oh" / "helix-backup").iterdir()
    assert (backup / "helixscreen" / "VERSION").read_text() == "old"
    assert (backup / "helixscreen" / "config" / "settings.json").exists()
    assert (backup / "init.d" / "S99helixscreen").read_text() == "#!/bin/sh\n# old\n"
    assert (backup / "init.d" / "helixscreen").is_file()


def test_helix_update_failure_leaves_the_setup_alone(tmp_path, monkeypatch):
    helix_tree(tmp_path, monkeypatch, "old")
    archive = release_archive(tmp_path)
    monkeypatch.setattr(setup, "print_state", lambda conf: "complete")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: Result(1))
    monkeypatch.setattr(setup, "point_helix", lambda *a: 1 / 0)
    assert setup.update_helix(CONF, str(archive)) == 1


def test_helix_restore_puts_the_saved_one_back_and_keeps_the_replaced(tmp_path, monkeypatch):
    helix, init_d = helix_tree(tmp_path, monkeypatch, "old")
    setup.save_helix(str(tmp_path / "k2oh" / "helix-backup" / "20261028-120000"))
    (helix / "VERSION").write_text("new")
    (init_d / "S99helixscreen").write_text("#!/bin/sh\n# new\n")
    monkeypatch.setattr(setup, "print_state", lambda conf: "standby")
    calls = []
    monkeypatch.setattr(setup, "stop_helix", lambda: calls.append("stop"))
    monkeypatch.setattr(setup, "disable_helix_camera", lambda: calls.append("camera"))
    monkeypatch.setattr(setup.subprocess, "run", lambda argv, **kw: calls.append(argv[1]))
    assert setup.restore_helix(CONF) == 0
    assert calls == ["stop", "camera", "start"]
    assert (helix / "VERSION").read_text() == "old"
    assert (init_d / "S99helixscreen").read_text() == "#!/bin/sh\n# old\n"
    (replaced,) = (tmp_path / "k2oh" / "trash").iterdir()
    assert (replaced / "VERSION").read_text() == "new"


def test_helix_restore_without_a_backup(tmp_path, monkeypatch):
    helix_tree(tmp_path, monkeypatch, "old")
    assert setup.restore_helix(CONF) == 1
