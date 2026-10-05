"""k2oh-bridge data path, tested with pipes and pseudo-terminals (Linux)."""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import pty
import select
import sys
import threading
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs ptys")


def load():
    loader = importlib.machinery.SourceFileLoader(
        "k2oh_bridge", str(ROOT / "rootfs/usr/bin/k2oh-bridge"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


br = load()


def nonblocking_pipe():
    r, w = os.pipe()
    os.set_blocking(w, False)
    return r, w


def test_direction_writes_immediately_and_records_delay():
    r, w = nonblocking_pipe()
    d = br.Direction("x", None, w)
    assert d.accept(b"hello") is False
    assert os.read(r, 100) == b"hello"
    assert d.bytes == 5 and d.reads == 1 and not d.pending
    assert sum(d.hist) == 0 and d.queued == 0  # straight through: not timed


def test_full_destination_queues_without_blocking_and_drains():
    r, w = nonblocking_pipe()
    d = br.Direction("x", None, w)
    big = b"a" * (1 << 20)
    assert d.accept(big) is True  # pipe takes ~64 KiB, the rest queues
    assert d.pending and d.short_writes + d.eagain >= 1 and d.queued == 1
    assert d.dropped > 0 and len(d.pending) <= br.MAX_PENDING
    assert d.accept(b"more") is False  # already queued: appended behind
    while d.pending:
        os.read(r, 1 << 16)
        d.drain()
    assert d.pending_since is None and d.max_pending == br.MAX_PENDING
    assert sum(d.hist) == 1


def run_bridge(a_slave, b_slave, stats_dir, extra=()):
    os.environ["K2OH_BRIDGE_STATS"] = str(stats_dir)
    br.STATS_DIR = str(stats_dir)
    br.running = True
    thread = threading.Thread(
        target=br.main, args=([a_slave, b_slave, *extra],), daemon=True)
    thread.start()
    time.sleep(0.3)
    return thread


def read_exactly(fd, n, timeout=5.0):
    data = b""
    end = time.monotonic() + timeout
    while len(data) < n and time.monotonic() < end:
        if select.select([fd], [], [], 0.1)[0]:
            data += os.read(fd, n - len(data))
    return data


def test_end_to_end_both_directions(tmp_path):
    a_master, a_slave = pty.openpty()
    b_master, b_slave = pty.openpty()
    thread = run_bridge(os.ttyname(a_slave), os.ttyname(b_slave), tmp_path,
                        ["--chunk", "256"])
    payload = bytes(range(256)) * 40
    os.write(a_master, payload)
    assert read_exactly(b_master, len(payload)) == payload
    os.write(b_master, b"\x7e\x00\x0d\x0a\xff")
    assert read_exactly(a_master, 5) == b"\x7e\x00\x0d\x0a\xff"  # no CR/LF mangling
    br.running = False
    thread.join(3)
    stats = json.loads((tmp_path / (os.path.basename(os.ttyname(a_slave)) + ".json")).read_text())
    assert stats["to_uart"]["bytes"] == len(payload)
    assert stats["to_host"]["bytes"] == 5
    assert stats["options"]["chunk"] == 256
    assert stats["to_uart"]["dropped"] == 0


def test_stalled_side_does_not_block_the_other(tmp_path):
    a_master, a_slave = pty.openpty()
    b_master, b_slave = pty.openpty()
    thread = run_bridge(os.ttyname(a_slave), os.ttyname(b_slave), tmp_path)
    # Nobody reads a_master: flood b -> a until a's side backs up.
    os.set_blocking(b_master, False)
    flood = b"z" * 4096
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.write(b_master, flood)
        except BlockingIOError:
            time.sleep(0.01)
    # The other direction still flows.
    os.write(a_master, b"ping")
    got = b""
    end = time.monotonic() + 3
    while b"ping" not in got and time.monotonic() < end:
        if select.select([b_master], [], [], 0.1)[0]:
            got += os.read(b_master, 4096)
    br.running = False
    thread.join(3)
    assert b"ping" in got


def test_eof_on_gadget_port_reopens_it(tmp_path, monkeypatch):
    # After a gadget unbind/rebind the old ttyGS descriptor only returns EOF;
    # the bridge must reopen the port instead of waiting on it forever.
    a_master, a_slave = pty.openpty()
    b_master, b_slave = pty.openpty()
    usb_rdev = os.fstat(a_slave).st_rdev
    real_read = os.read
    state = {"eof": False}

    def fake_read(fd, n):
        if not state["eof"] and os.fstat(fd).st_rdev == usb_rdev:
            state["eof"] = True
            return b""
        return real_read(fd, n)

    monkeypatch.setattr(br.os, "read", fake_read)
    thread = run_bridge(os.ttyname(a_slave), os.ttyname(b_slave), tmp_path)
    os.write(a_master, b"x")  # wakes the bridge; its read sees the EOF
    time.sleep(0.5)  # reopened (the reopen flushes the stale input)
    os.write(a_master, b"after-reopen")
    assert read_exactly(b_master, 12) == b"after-reopen"
    br.running = False
    thread.join(3)
    stats = json.loads((tmp_path / (os.path.basename(os.ttyname(a_slave)) + ".json")).read_text())
    assert state["eof"] and stats["to_uart"]["reopens"] == 1
