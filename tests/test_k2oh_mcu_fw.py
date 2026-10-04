"""k2oh-mcu-fw host checks and apply flow, with every hardware call mocked.

No test opens a UART, writes a GPIO or calls systemctl: run_live, the
Moonraker query and the printer identity are replaced.
"""

import base64
import importlib.machinery
import importlib.util
import io
import json
import pathlib
import socket
import types
import urllib.error

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = 1_800_000_000
SERIAL = "TESTSERIAL0001"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


fw = load("k2oh_mcu_fw", ROOT / "rootfs/usr/bin/k2oh-mcu-fw")


def evidence(**changes):
    data = {
        "v": 1,
        "checked_at": NOW - 30,
        "host": "testhost",
        "root": True,
        "klipper_service": "inactive",
        "klippy_processes": [],
        "fd_scan_complete": True,
        "ports": [
            {"device": "/dev/ttyUSB%d" % n, "serial": SERIAL, "interface": "0%d" % n, "owners": []}
            for n in range(3)
        ],
    }
    data.update(changes)
    return data


def encode(data):
    return base64.b64encode(json.dumps(data).encode()).decode()


# --- Moonraker --------------------------------------------------------------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answer(body):
    def urlopen(_url, timeout):
        return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())
    return urlopen


def raising(exc):
    def urlopen(_url, timeout):
        raise exc
    return urlopen


@pytest.mark.parametrize("urlopen, status", [
    (raising(urllib.error.URLError(socket.timeout("timed out"))), "timeout"),
    (raising(socket.timeout("timed out")), "timeout"),
    (raising(urllib.error.URLError(ConnectionRefusedError(111, "refused"))), "unreachable"),
    (raising(urllib.error.HTTPError("u", 503, "busy", {}, None)), "http_error"),
    (answer(b"<html>not json</html>"), "malformed"),
    (answer({"result": {}}), "malformed"),
    (answer({"result": {"klippy_connected": "no", "klippy_state": "disconnected"}}), "malformed"),
    (answer({"result": {"klippy_connected": False, "klippy_state": "weird"}}), "malformed"),
    (answer({"result": {"klippy_connected": True, "klippy_state": "ready"}}), "active"),
    (answer({"result": {"klippy_connected": True, "klippy_state": "startup"}}), "active"),
    (answer({"result": {"klippy_connected": True, "klippy_state": "shutdown"}}), "active"),
    (answer({"result": {"klippy_connected": False, "klippy_state": "error"}}), "active"),
    (answer({"result": {"klippy_connected": False, "klippy_state": "disconnected"}}), "stopped"),
])
def test_moonraker_state(monkeypatch, urlopen, status):
    monkeypatch.setattr(fw.urllib.request, "urlopen", urlopen)
    assert fw.moonraker_state("http://host:7125")["status"] == status


def test_moonraker_without_url_is_not_a_stop():
    assert fw.moonraker_state(None)["status"] == "no_config"


# --- host proof -------------------------------------------------------------

def test_good_proof_has_no_blockers():
    assert fw.evidence_blockers(evidence(), SERIAL, NOW) == []


@pytest.mark.parametrize("changes, words", [
    ({"v": 2}, "version"),
    ({"checked_at": NOW - 5000}, "old"),
    ({"checked_at": NOW + 3600}, "future"),
    ({"checked_at": None}, "no time"),
    ({"checked_at": float("nan")}, "no time"),
    ({"root": False}, "every process"),
    ({"fd_scan_complete": False}, "every process"),
    ({"klipper_service": "active"}, "not stopped"),
    ({"klipper_service": "activating"}, "not stopped"),
    ({"klipper_service": "unknown"}, "not stopped"),
    ({"klippy_processes": [1234]}, "still runs"),
    ({"klippy_processes": None}, "does not list klippy"),
    ({"ports": None}, "does not list the gadget"),
    ({"ports": []}, "does not see this printer"),
])
def test_proof_blockers(changes, words):
    reasons = fw.evidence_blockers(evidence(**changes), SERIAL, NOW)
    assert any(words in r for r in reasons), reasons


def test_proof_from_another_printer_blocks():
    reasons = fw.evidence_blockers(evidence(), "OTHERSERIAL", NOW)
    assert any("does not see this printer" in r for r in reasons)


def test_unknown_printer_serial_blocks():
    assert fw.evidence_blockers(evidence(), "", NOW)


def test_missing_interface_blocks():
    data = evidence()
    data["ports"] = data["ports"][:2]
    assert any("interfaces 00, 01" in r for r in fw.evidence_blockers(data, SERIAL, NOW))


def test_open_port_blocks():
    data = evidence()
    data["ports"][1]["owners"] = [4321]
    assert any("open on the host (pid 4321)" in r for r in fw.evidence_blockers(data, SERIAL, NOW))


def test_unknown_owners_block():
    data = evidence()
    data["ports"][2]["owners"] = None
    assert any("owners unknown" in r for r in fw.evidence_blockers(data, SERIAL, NOW))


@pytest.mark.parametrize("text", [None, "", "not base64 !!", base64.b64encode(b"[1, 2]").decode()])
def test_bad_proof_text(text):
    data, problem = fw.decode_evidence(text)
    assert data is None and problem


# --- apply ------------------------------------------------------------------

class Calls:
    def __init__(self, codes=None):
        self.cmds = []
        self.codes = codes or {}

    def __call__(self, cmd, env=None):
        key = " ".join(cmd)
        self.cmds.append(key)
        return self.codes.get(key, 0)

    def flashed(self):
        return any("mcu_reset" in c or "mcu_update" in c for c in self.cmds)


BRIDGE_STOP = "/etc/init.d/k2oh-bridge stop"
BRIDGE_START = "/etc/init.d/k2oh-bridge start"
RESET = "/usr/bin/mcu_reset.sh"
UPDATE = "/etc/init.d/mcu_update start"


@pytest.fixture
def apply_env(monkeypatch, tmp_path):
    calls = Calls()
    state = {"moonraker": {"status": "stopped", "detail": "Klippy is disconnected"},
             "plan": [("Main", "mcu0_120_G32-mcu0_001_000", "up to date", "mcu0_120_G32-mcu0_001_000")],
             "answer": "flash"}
    monkeypatch.setattr(fw, "require_slot_b", lambda: None)
    monkeypatch.setattr(fw, "model_dir", lambda: "F012")
    monkeypatch.setattr(fw, "moonraker_state", lambda url, timeout=5: dict(state["moonraker"]))
    monkeypatch.setattr(fw, "printer_serial", lambda: SERIAL)
    monkeypatch.setattr(fw, "run_live", calls)
    monkeypatch.setattr(fw, "board_plan", lambda model: list(state["plan"]))
    monkeypatch.setattr(fw, "cmd_status", lambda args: None)
    monkeypatch.setattr(fw, "read_staged", lambda: None)
    monkeypatch.setattr(fw, "CFS_JSON", str(tmp_path / "cfs_update.json"))
    monkeypatch.setattr(fw.time, "time", lambda: NOW)
    monkeypatch.setattr("builtins.input", lambda prompt="": state["answer"])
    return calls, state


def args(proof=None, yes=False, cfs=False):
    return types.SimpleNamespace(host_evidence=proof, moonraker="http://host:7125", yes=yes, cfs=cfs)


@pytest.mark.parametrize("status", ["timeout", "unreachable", "http_error", "malformed", "no_config", "active"])
def test_apply_blocks_unless_moonraker_says_stopped(apply_env, status):
    calls, state = apply_env
    state["moonraker"] = {"status": status, "detail": "x"}
    with pytest.raises(SystemExit) as exc:
        fw.cmd_apply(args(encode(evidence()), yes=True))
    assert exc.value.code != 0
    assert calls.cmds == []


def test_apply_blocks_without_proof_even_with_yes(apply_env):
    calls, _state = apply_env
    with pytest.raises(SystemExit):
        fw.cmd_apply(args(None, yes=True))
    assert calls.cmds == []


def test_apply_blocks_when_klipper_holds_the_ports(apply_env):
    calls, state = apply_env
    state["moonraker"] = {"status": "active", "detail": "Klippy is shutdown"}
    data = evidence(klipper_service="active", klippy_processes=[999])
    data["ports"][0]["owners"] = [999]
    with pytest.raises(SystemExit):
        fw.cmd_apply(args(encode(data), yes=True))
    assert calls.cmds == []


def test_apply_reaches_confirmation_and_can_be_cancelled(apply_env):
    calls, state = apply_env
    state["answer"] = "no"
    with pytest.raises(SystemExit):
        fw.cmd_apply(args(encode(evidence())))
    assert calls.cmds == []


def test_apply_success(apply_env):
    calls, _state = apply_env
    fw.cmd_apply(args(encode(evidence())))
    assert calls.cmds == [BRIDGE_STOP, RESET, UPDATE, BRIDGE_START]


def test_failed_updater_exits_non_zero_and_restores_bridges(apply_env, capsys):
    calls, _state = apply_env
    calls.codes[UPDATE] = 1
    with pytest.raises(SystemExit) as exc:
        fw.cmd_apply(args(encode(evidence())))
    assert exc.value.code != 0
    assert calls.cmds == [BRIDGE_STOP, RESET, UPDATE, BRIDGE_START]
    assert "mcu_update failed" in capsys.readouterr().err


def test_failed_reset_skips_the_updater(apply_env):
    calls, _state = apply_env
    calls.codes[RESET] = 2
    with pytest.raises(SystemExit):
        fw.cmd_apply(args(encode(evidence())))
    assert UPDATE not in calls.cmds
    assert calls.cmds[-1] == BRIDGE_START


def test_failed_bridge_stop_never_resets(apply_env):
    calls, _state = apply_env
    calls.codes[BRIDGE_STOP] = 1
    with pytest.raises(SystemExit):
        fw.cmd_apply(args(encode(evidence())))
    assert not calls.flashed()
    assert calls.cmds == [BRIDGE_STOP, BRIDGE_START]


def test_failed_bridge_restore_is_an_error(apply_env, capsys):
    calls, _state = apply_env
    calls.codes[BRIDGE_START] = 1
    with pytest.raises(SystemExit) as exc:
        fw.cmd_apply(args(encode(evidence())))
    assert exc.value.code != 0
    assert "bridges did not start again" in capsys.readouterr().err


def test_board_still_different_after_flash_is_an_error(apply_env, capsys):
    _calls, state = apply_env
    state["plan"] = [("Nozzle", "noz0_130_G30-noz0_020_000", "-> noz0_130_G30-noz0_021_000",
                      "noz0_130_G30-noz0_021_000")]
    with pytest.raises(SystemExit):
        fw.cmd_apply(args(encode(evidence())))
    assert "still differ" in capsys.readouterr().err


def test_cfs_difference_without_cfs_pass_is_not_a_failure(apply_env):
    calls, state = apply_env
    state["plan"] = [("cfs@1", "cfs0_050_G32-cfs0_000_113", "-> cfs0_050_G32-cfs0_000_150",
                      "cfs0_050_G32-cfs0_000_150")]
    fw.cmd_apply(args(encode(evidence())))
    assert calls.cmds[-1] == BRIDGE_START


# --- host proof generator ---------------------------------------------------

def test_generator_output_is_accepted(monkeypatch):
    gen = load("k2oh_host_evidence", ROOT / "host/k2oh-host-evidence")
    monkeypatch.setattr(gen, "gadget_ports", lambda: [
        {"device": "/dev/ttyUSB%d" % n, "serial": SERIAL, "interface": "0%d" % n} for n in range(3)])
    monkeypatch.setattr(gen, "owners", lambda devices: ({d: [] for d in devices}, True))
    monkeypatch.setattr(gen, "service_state", lambda unit: "inactive")
    monkeypatch.setattr(gen, "klippy_processes", lambda: [])
    monkeypatch.setattr(gen.time, "time", lambda: NOW)
    monkeypatch.setattr(gen.os, "geteuid", lambda: 0, raising=False)
    data = gen.collect("klipper")
    decoded, problem = fw.decode_evidence(encode(data))
    assert problem is None
    assert fw.evidence_blockers(decoded, SERIAL, NOW) == []
