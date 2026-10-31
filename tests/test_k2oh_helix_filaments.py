"""k2oh-helix-filaments: HelixScreen catalog from the Kalico library."""

import importlib.machinery
import importlib.util
import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader(
        "k2oh_helix_filaments", str(ROOT / "rootfs/usr/bin/k2oh-helix-filaments"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


hf = load()

SHIPPED = {
    "_attribution": "Orca-derived facts",
    "orca_library_types": ["PLA", "PETG"],
    "orca_type_overrides": {"PLA+": "PLA"},
    "filaments": [{"id": "bambu-lab-bambu-abs", "brand": "Bambu Lab",
                   "name": "Bambu ABS", "type": "ABS", "source": "orca"}],
}

LIBRARY = {
    "07001": {"id": "07001", "material": "ABS", "brand": "Creality", "name": "CR-ABS",
              "target_temp": 260, "min_temp": 240, "max_temp": 280,
              "rfid_code": "07001", "system": True},
    "05628": {"id": "05628", "material": "PLA", "brand": "Bambulab",
              "name": "Bambulab PLA Basic", "color": "#808080", "target_temp": 215,
              "min_temp": None, "max_temp": None, "rfid_code": "05628",
              "system": False},
}


class FakeMoonraker:
    def __init__(self, library, state="standby"):
        self.lib = json.loads(json.dumps(library))
        self.state = state
        self.scripts = []

    def library(self):
        return json.loads(json.dumps(self.lib))

    def print_state(self):
        return self.state

    def gcode(self, script):
        self.scripts.append(script)
        # mimic Kalico: the filament appears in the library
        fields = dict(part.split("=", 1) for part in script.split()[1:] if "=" in part)
        kid = fields["ID"]
        self.lib[kid] = {"id": kid, "material": fields["MATERIAL"], "brand": "",
                         "name": kid, "system": False}
        return True


@pytest.fixture
def helix(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "assets/filaments.json").write_text(json.dumps(SHIPPED))
    (tmp_path / "config/user_filaments.json").write_text("[]")
    return hf.paths(str(tmp_path))


def read(path):
    return json.loads(pathlib.Path(path).read_text())


def test_catalog_lists_only_the_host_library(helix):
    assert hf.sync_catalog(helix, LIBRARY) is True
    doc = read(helix["asset"])
    names = [p["name"] for p in doc["filaments"]]
    assert names == ["Bambulab PLA Basic", "CR-ABS"]  # no shipped presets left
    assert doc["orca_library_types"] == ["PLA", "PETG"]  # type tables kept
    abs_ = next(p for p in doc["filaments"] if p["name"] == "CR-ABS")
    assert abs_ == {"id": "k2oh-07001", "brand": "Creality", "name": "CR-ABS",
                    "type": "ABS", "source": "k2openhost", "nozzle": 260,
                    "nozzle_min": 240, "nozzle_max": 280, "codes": {"cfs": "07001"}}
    pla = next(p for p in doc["filaments"] if p["type"] == "PLA")
    assert "nozzle_min" not in pla  # unknown limits come from the type
    assert read(helix["orig"]) == SHIPPED


def test_unchanged_library_does_not_rewrite(helix):
    assert hf.sync_catalog(helix, LIBRARY)
    before = os.stat(helix["asset"]).st_mtime_ns
    assert hf.sync_catalog(helix, LIBRARY) is False
    assert os.stat(helix["asset"]).st_mtime_ns == before


def test_helix_update_becomes_the_new_original(helix):
    hf.sync_catalog(helix, LIBRARY)
    updated = dict(SHIPPED, orca_library_types=["PLA", "PETG", "TPU"])
    pathlib.Path(helix["asset"]).write_text(json.dumps(updated))  # HelixScreen update
    assert hf.sync_catalog(helix, LIBRARY) is True
    assert read(helix["orig"])["orca_library_types"] == ["PLA", "PETG", "TPU"]
    assert read(helix["asset"])["orca_library_types"] == ["PLA", "PETG", "TPU"]


def test_restore_puts_the_shipped_catalog_back(helix):
    hf.sync_catalog(helix, LIBRARY)
    assert hf.restore(helix) is True
    assert read(helix["asset"]) == SHIPPED
    assert not os.path.exists(helix["orig"])


def test_new_helix_product_is_sent_to_kalico_and_dropped(helix):
    pathlib.Path(helix["overlay"]).write_text(json.dumps({
        "types": [{"name": "PLA", "bed": 60}],
        "filaments": [{"id": "user-1", "brand": "Sunlu", "name": "Sunlu PLA+ Grey",
                       "type": "PLA", "nozzle": 215, "nozzle_min": 200,
                       "nozzle_max": 230}]}))
    mr = FakeMoonraker(LIBRARY)
    assert hf.import_overlay(helix, mr.library(), mr) == 1
    assert mr.scripts == ['_BOX_FILAMENT_SET ID=HX0001 MATERIAL=PLA BRAND="Sunlu" '
                          'NAME="Sunlu PLA+ Grey" TARGET_TEMP=215 MIN_TEMP=200 MAX_TEMP=230']
    overlay = read(helix["overlay"])
    assert overlay["filaments"] == [] and overlay["types"] == [{"name": "PLA", "bed": 60}]


def test_edit_of_custom_kalico_product_is_pushed_system_stays_local(helix):
    pathlib.Path(helix["overlay"]).write_text(json.dumps([
        {"id": "k2oh-05628", "name": "Bambulab PLA Basic Grey", "nozzle": 220},
        {"id": "k2oh-07001", "nozzle": 250}]))
    mr = FakeMoonraker(LIBRARY)
    assert hf.import_overlay(helix, mr.library(), mr) == 1
    assert mr.scripts[0].startswith("_BOX_FILAMENT_SET ID=05628 MATERIAL=PLA")
    assert 'NAME="Bambulab PLA Basic Grey"' in mr.scripts[0]
    assert "COLOR=#808080" in mr.scripts[0]  # the Kalico colour is kept
    assert read(helix["overlay"]) == [{"id": "k2oh-07001", "nozzle": 250}]


def test_nothing_is_imported_while_printing(helix):
    pathlib.Path(helix["overlay"]).write_text(json.dumps([
        {"id": "user-1", "name": "X", "type": "PLA"}]))
    mr = FakeMoonraker(LIBRARY, state="printing")
    state = {}
    idle = hf.run_once(helix, mr, state, restart_mode="never")
    assert idle is False and mr.scripts == []
    assert len(read(helix["overlay"])) == 1
    assert state["restart_pending"] is True  # catalog written, restart deferred


def test_restart_only_when_idle(helix, monkeypatch):
    restarts = []
    monkeypatch.setattr(hf, "restart_helix", lambda: restarts.append(1))
    mr = FakeMoonraker(LIBRARY, state="printing")
    state = {}
    hf.run_once(helix, mr, state)
    assert restarts == []
    mr.state = "standby"
    hf.run_once(helix, mr, state)
    assert restarts == [1] and state["restart_pending"] is False
    hf.run_once(helix, mr, state)
    assert restarts == [1]  # no change, no restart


def test_gcode_values_are_sanitised():
    cmd = hf.filament_set_command("HX0001", {
        "type": "PLA", "brand": 'Evil"; M112', "name": "a\nb", "nozzle": 999})
    assert '"' not in cmd.split('BRAND="', 1)[1].split('"', 1)[0]
    assert ";" not in cmd and "\n" not in cmd
    assert "TARGET_TEMP=350" in cmd
    assert hf.filament_set_command("HX0002", {"name": "no type"}) is None


def test_new_ids_skip_taken_ones():
    lib = {"HX0001": {}, "hx0002": {}}
    assert hf.next_new_id(lib, []) == "HX0003"
    assert hf.next_new_id(lib, ["HX0003"]) == "HX0004"


def release(helix, version):
    pathlib.Path(helix["release"]).write_text(json.dumps({"version": version}))


@pytest.mark.parametrize("version,native", [
    ("v1.0.6-k2oh.8", True), ("v1.0.6-k2oh.12", True), ("v1.1.0-k2oh.8", True),
    ("v1.0.6-k2oh.7", False), ("v1.0.6", False), ("", False)])
def test_native_helix_is_recognised(helix, version, native):
    release(helix, version)
    assert hf.helix_reads_library(helix) is native


def test_no_release_info_keeps_the_service(helix):
    assert hf.retire(helix) is False


def test_retire_restores_the_shipped_catalog(helix):
    hf.sync_catalog(helix, LIBRARY)
    release(helix, "v1.0.6-k2oh.8")
    assert hf.retire(helix) is True
    assert read(helix["asset"]) == SHIPPED
    assert not os.path.exists(helix["orig"])
    assert hf.retire(helix) is True  # nothing left to restore, still retired


def test_retire_flag_exit_codes(helix, monkeypatch):
    monkeypatch.setattr(hf, "paths", lambda helix_dir=None: helix)
    assert hf.main(["--retire"]) == 1
    release(helix, "v1.0.6-k2oh.8")
    assert hf.main(["--retire"]) == 0
