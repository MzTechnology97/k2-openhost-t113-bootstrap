"""k2oh-ctl with a fake GPIO tree, fake commands and a fake Moonraker.

Nothing here touches real GPIOs, services or the network: the HTTP tests
bind to 127.0.0.1 on a free port.
"""

import importlib.machinery
import importlib.util
import json
import pathlib
import threading
import urllib.error
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ctl_mod = load("k2oh_ctl", ROOT / "rootfs/usr/bin/k2oh-ctl")
TOKEN = "test-token-0123456789abcdef"


@pytest.fixture
def gpio(tmp_path):
    for number in (140, 164):
        d = tmp_path / ("gpio%d" % number)
        d.mkdir()
        (d / "direction").write_text("out\n")
        (d / "value").write_text("0\n")
    return ctl_mod.Gpio(str(tmp_path)), tmp_path


def value(root, number):
    return (root / ("gpio%d" % number) / "value").read_text().strip()


class Host:
    """Fake Moonraker answers, by scenario."""

    def __init__(self, klippy="ready", print_state="standby", fail=False):
        self.klippy = klippy
        self.print_state = print_state
        self.fail = fail

    def __call__(self, path):
        if self.fail:
            raise OSError("connection refused")
        if path == "/server/info":
            return {"klippy_state": self.klippy}
        return {"status": {"print_stats": {"state": self.print_state}}}


class Recorder:
    def __init__(self, codes=None, gpio_root=None, log=None):
        self.cmds = []
        self.codes = codes or {}
        self.gpio_root = gpio_root
        self.log = log

    def __call__(self, argv):
        key = " ".join(argv)
        self.cmds.append(key)
        if self.log is not None:
            self.log.append(("cmd", key, value(self.gpio_root, 140)))
        return self.codes.get(key, 0)


def controller(gpio_fixture, host=None, codes=None):
    gpio, root = gpio_fixture
    log = []
    runner = Recorder(codes, root, log)

    def sleep(seconds):
        log.append(("sleep", seconds, value(root, 140)))

    ctl = ctl_mod.Controller({"MOONRAKER_URL": "http://host:7125"}, gpio=gpio,
                             runner=runner, clock=lambda: 100.0, sleep=sleep,
                             moonraker=host or Host())
    return ctl, runner, log, root


STOP = "/etc/init.d/k2oh-bridge stop"
START = "/etc/init.d/k2oh-bridge start"


def test_power_status(gpio):
    ctl, _r, _l, root = controller(gpio)
    assert ctl.mcu_power("status") == {"state": "on"}
    (root / "gpio140" / "value").write_text("1\n")
    assert ctl.mcu_power("status") == {"state": "off"}


def test_cycle_sequence(gpio):
    ctl, runner, log, root = controller(gpio)
    result = ctl.mcu_cycle()
    assert runner.cmds == [STOP, START]
    # bridges stopped with power on, rail off for 2 s, back on, then bridges
    assert log == [
        ("cmd", STOP, "0"),
        ("sleep", 2.0, "1"),
        ("sleep", 1.0, "0"),
        ("cmd", START, "0"),
    ]
    assert result["state"] == "on" and value(root, 140) == "0"
    assert ctl.last_action["action"] == "mcu_cycle"


@pytest.mark.parametrize("host, words", [
    (Host(print_state="printing"), "printing"),
    (Host(print_state="paused"), "paused"),
    (Host(print_state="weird"), "weird"),
    (Host(fail=True), "unreachable"),
    (Host(klippy="startup"), "startup"),
])
def test_cycle_refused_unless_idle(gpio, host, words):
    ctl, runner, _log, root = controller(gpio, host)
    with pytest.raises(PermissionError, match=words):
        ctl.mcu_cycle()
    assert runner.cmds == [] and value(root, 140) == "0"


def test_force_only_when_klippy_is_shut_down(gpio):
    ctl, runner, _l, _root = controller(gpio, Host(klippy="shutdown"))
    with pytest.raises(PermissionError):
        ctl.mcu_cycle()
    ctl.mcu_cycle(force=True)
    assert runner.cmds == [STOP, START]
    ctl2, runner2, _l2, _r2 = controller(gpio, Host(print_state="printing"))
    with pytest.raises(PermissionError):
        ctl2.mcu_cycle(force=True)
    assert runner2.cmds == []


def test_cycle_restores_power_even_if_sleep_fails(gpio):
    ctl, _r, _l, root = controller(gpio)

    def boom(seconds):
        if seconds == ctl_mod.CYCLE_OFF_SECONDS:
            raise KeyboardInterrupt
    ctl.sleep = boom
    with pytest.raises(KeyboardInterrupt):
        ctl.mcu_cycle()
    assert value(root, 140) == "0"


def test_cycle_reports_bridge_failure(gpio):
    ctl, _r, _l, root = controller(gpio, codes={START: 1})
    with pytest.raises(RuntimeError, match="bridge start failed"):
        ctl.mcu_cycle()
    assert value(root, 140) == "0"


def test_power_off_and_on(gpio):
    ctl, runner, _l, root = controller(gpio)
    assert ctl.mcu_power("off")["state"] == "off"
    assert value(root, 140) == "1" and runner.cmds == [STOP]
    assert ctl.mcu_power("on")["state"] == "on"
    assert value(root, 140) == "0" and runner.cmds == [STOP, START]


def test_power_off_refused_while_printing(gpio):
    ctl, runner, _l, root = controller(gpio, Host(print_state="printing"))
    with pytest.raises(PermissionError):
        ctl.mcu_power("off")
    assert value(root, 140) == "0" and runner.cmds == []


def test_power_on_needs_no_host(gpio):
    ctl, _r, _l, root = controller(gpio, Host(fail=True))
    (root / "gpio140" / "value").write_text("1\n")
    assert ctl.mcu_power("on")["state"] == "on"


def test_estop_needs_nothing(gpio):
    ctl, runner, _l, root = controller(gpio, Host(fail=True))
    assert ctl.estop() == {"state": "off"}
    assert value(root, 140) == "1" and runner.cmds == []


def test_never_changes_direction(gpio):
    ctl, _r, _l, root = controller(gpio)
    (root / "gpio140" / "direction").write_text("in\n")
    with pytest.raises(RuntimeError, match="not an output"):
        ctl.estop()
    assert (root / "gpio140" / "direction").read_text().strip() == "in"


def test_bad_power_command(gpio):
    ctl, _r, _l, _root = controller(gpio)
    with pytest.raises(ValueError):
        ctl.mcu_power("toggle")


def test_beep_is_bounded_and_ends_off(gpio):
    ctl, _r, _l, root = controller(gpio)
    states = []
    ctl.sleep = lambda s: states.append((s, value(root, 164)))
    result = ctl.beep(ms=99999, count=50)
    assert result == {"queued": True, "ms": 3000, "count": 5}
    for _ in range(100):
        if ctl.beep_lock.acquire(False):
            ctl.beep_lock.release()
            break
        threading.Event().wait(0.01)
    assert value(root, 164) == "0"
    assert [s for s in states if s[1] == "1"] == [(3.0, "1")] * 5


def test_bridges_restart(gpio):
    ctl, runner, _l, _root = controller(gpio)
    ctl.bridges_restart()
    assert runner.cmds == ["/etc/init.d/k2oh-bridge restart"]


def test_bridge_commands_can_be_configured(gpio):
    ctl, runner, _l, _root = controller(gpio)
    ctl.conf["BRIDGE_STOP_CMD"] = "/tmp/bridges.sh stop"
    ctl.conf["BRIDGE_START_CMD"] = "/tmp/bridges.sh start"
    ctl.mcu_cycle()
    assert runner.cmds == ["/tmp/bridges.sh stop", "/tmp/bridges.sh start"]


def test_bridge_status_from_stats(tmp_path, monkeypatch):
    stats = tmp_path / "stats"
    stats.mkdir()
    (stats / "ttyGS2.json").write_text(json.dumps({
        "pid": 1, "host_bytes": 10, "uart_bytes": 20,
        "last_host_rx": 95.0, "last_uart_rx": 99.5, "updated": 99.9}))
    monkeypatch.setattr(ctl_mod, "BRIDGE_STATS", str(stats))
    status = ctl_mod.bridge_status(100.0)
    assert status["rs485"]["host_rx_age_s"] == 5.0
    assert status["rs485"]["uart_bytes"] == 20
    assert status["main"]["alive"] is False and status["main"]["host_bytes"] is None


def test_status_is_serializable(gpio):
    ctl, _r, _l, _root = controller(gpio)
    json.dumps(ctl.status())


# --- HTTP ----------------------------------------------------------------------

@pytest.fixture
def server(gpio):
    ctl, runner, _log, root = controller(gpio)
    srv = ctl_mod.Server(("127.0.0.1", 0), ctl_mod.make_handler(ctl, TOKEN, {"127.0.0.1"}))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1], ctl, runner, root
    srv.shutdown()


def call(base, path, body=None, token=TOKEN):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET")
    if token:
        req.add_header("X-K2OH-Token", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_http_requires_token(server):
    base, _ctl, runner, root = server
    assert call(base, "/status", token=None)[0] == 401
    assert call(base, "/estop", {}, token="wrong-token-0000000000")[0] == 401
    assert value(root, 140) == "0" and runner.cmds == []


def test_http_rejects_other_hosts(gpio):
    ctl, _r, _l, root = controller(gpio)
    srv = ctl_mod.Server(("127.0.0.1", 0), ctl_mod.make_handler(ctl, TOKEN, {"10.0.0.9"}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, body = call("http://127.0.0.1:%d" % srv.server_address[1], "/estop", {})
    finally:
        srv.shutdown()
    assert code == 403 and value(root, 140) == "0"


def test_http_moonraker_power_device_contract(server):
    # What Moonraker's generic "http" power device sends with the template
    # documented in docs: POST {"command": on|off|status}, reads "state".
    base, _ctl, _runner, root = server
    assert call(base, "/power/mcu", {"command": "status"}) == (200, {"state": "on"})
    code, body = call(base, "/power/mcu", {"command": "off"})
    assert code == 200 and body["state"] == "off" and value(root, 140) == "1"
    code, body = call(base, "/power/mcu", {"command": "on"})
    assert code == 200 and body["state"] == "on"


def test_http_refusal_is_409(server):
    base, ctl, runner, root = server
    ctl.moonraker = Host(print_state="printing")
    code, body = call(base, "/mcu/cycle", {})
    assert code == 409 and "printing" in body["error"]
    assert runner.cmds == [] and value(root, 140) == "0"


def test_http_bad_requests(server):
    base, *_ = server
    assert call(base, "/power/mcu", {"command": "toggle"})[0] == 400
    assert call(base, "/nothing", {})[0] == 404
    code, body = call(base, "/status")
    assert code == 200 and body["mcu_power"] == "on"
