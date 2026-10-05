"""k2oh-linkstat: one CSV row from two snapshots."""

import importlib.machinery
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader(
        "k2oh_linkstat", str(ROOT / "rootfs/usr/bin/k2oh-linkstat"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ls = load()


def snap(t, busy, ctxt, udc, uart_bo, bridge_cpu, bridge_bytes):
    return {
        "t": t,
        "cpu": ({"cpu0": (1000 + t * 100, 1000 + t * 100 - busy),
                 "cpu1": (1000 + t * 100, 1000 + t * 100)}, ctxt),
        "irq": {"sunxi_usb_udc": [udc, 0], "uart2": [10 * t, 0],
                "uart3": [5 * t, 0], "uart5": [t, 0]},
        "soft": {"NET_RX": 0, "TASKLET": 2 * t, "TIMER": 100 * t},
        "uart": {"main": {"rx": 100 * t, "tx": 50 * t, "fe": 0, "oe": 0, "bo": uart_bo, "brk": 0}},
        "bridges": {
            "main": (42, (bridge_cpu, 10 * t, t, 9000),
                     {"to_uart": {"bytes": bridge_bytes, "queued": 0}}),
            "nozzle": (None, None, {}),
            "rs485": (None, None, {}),
        },
    }


def test_row_rates_and_deltas(monkeypatch):
    monkeypatch.setattr(ls, "read", lambda path, default="": "configured" if "udc" in path else default)
    monkeypatch.setattr(ls.glob, "glob", lambda pattern: ["/sys/class/udc/x/state"] if "udc" in pattern else [])
    a = snap(0, 0, 1000, 500, 3, 1.0, 100)
    b = snap(10, 250, 21000, 1500, 5, 1.5, 900)
    fields = dict(ls.row(a, b))
    assert fields["cpu0_pct"] == "25.0" and fields["cpu1_pct"] == "0.0"
    assert fields["ctxt_per_s"] == "2000"
    assert fields["sunxi_usb_udc_irq_per_s"] == "100"
    assert fields["sunxi_usb_udc_cpus"] == "1500/0"
    assert fields["uart_main_bo"] == 2  # a delta, not the lifetime counter
    assert fields["uart_nozzle_bo"] == ""  # port not reported
    assert fields["udc_state"] == "configured"
    assert fields["main_cpu_pct"] == "5.00"
    assert fields["main_ctx_vol"] == 100 and fields["main_ctx_invol"] == 10
    assert fields["main_to_uart_bytes"] == 900 and fields["main_to_uart_queued"] == 0
    assert fields["nozzle_cpu_pct"] == ""


def test_bridge_restart_does_not_produce_a_rate(monkeypatch):
    monkeypatch.setattr(ls, "read", lambda path, default="": default)
    a = snap(0, 0, 0, 0, 0, 5.0, 0)
    b = snap(10, 0, 0, 0, 0, 0.1, 0)
    b["bridges"]["main"] = (43,) + b["bridges"]["main"][1:]
    assert dict(ls.row(a, b))["main_cpu_pct"] == ""
