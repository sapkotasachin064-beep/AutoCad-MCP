"""Units policy, pending-command handling and document pinning at the
cad_engine.get_active_document choke point -- against recorded fakes, not
AutoCAD (defects D4/D5 and the pinning gap in docs/analysis/gap-analysis.md)."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cad_engine
from core import session
from core.errors import CadError, ConfigError
from tools import primitives


class FakeDoc:
    def __init__(self, variables=None, name="Drawing1.dwg", full_name=""):
        self.vars = {"CMDACTIVE": 0, **(variables or {})}
        self.set_calls = []
        self.sent = []
        self.Name = name
        self.FullName = full_name

    def GetVariable(self, name):
        return self.vars.get(name, 0)

    def SetVariable(self, name, value):
        self.set_calls.append((name, value))
        self.vars[name] = value

    def SendCommand(self, text):
        self.sent.append(text)


def _app(doc):
    return SimpleNamespace(Documents=SimpleNamespace(Count=1), ActiveDocument=doc)


METRIC = {"LUNITS": 2, "LUPREC": 0, "INSUNITS": 4, "MEASUREMENT": 1}
ENGINEERING = {"LUNITS": 3, "LUPREC": 4, "INSUNITS": 1, "MEASUREMENT": 0}


@pytest.fixture(autouse=True)
def _clean_session(monkeypatch):
    monkeypatch.delenv("AUTOCAD_MCP_UNITS", raising=False)
    session.unpin_document()
    yield
    session.unpin_document()


def _collect(func):
    return session.collect(func)


def test_write_applies_default_engineering_preset_and_reports_it():
    doc = FakeDoc(METRIC)
    _, notices = _collect(lambda: cad_engine.get_active_document(_app(doc)))
    assert doc.vars["INSUNITS"] == 1 and doc.vars["LUNITS"] == 3 and doc.vars["MEASUREMENT"] == 0
    assert notices == [{
        "kind": "units_changed",
        "preset": "engineering",
        "variables": {
            "LUNITS": {"from": 2, "to": 3},
            "LUPREC": {"from": 0, "to": 4},
            "INSUNITS": {"from": 4, "to": 1},
            "MEASUREMENT": {"from": 1, "to": 0},
        },
    }]


def test_write_skips_variables_that_already_match():
    doc = FakeDoc(ENGINEERING)
    _, notices = _collect(lambda: cad_engine.get_active_document(_app(doc)))
    assert doc.set_calls == []
    assert notices == []


def test_read_only_access_never_changes_units_or_sends_keys():
    doc = FakeDoc({**METRIC, "CMDACTIVE": 1})
    _, notices = _collect(lambda: cad_engine.get_active_document(_app(doc), for_write=False))
    assert doc.set_calls == [] and doc.sent == []
    assert notices[0]["kind"] == "autocad_command_active"


def test_preserve_policy_never_touches_units(monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_UNITS", "preserve")
    doc = FakeDoc(METRIC)
    _collect(lambda: cad_engine.get_active_document(_app(doc)))
    assert doc.set_calls == []


def test_metric_mm_policy(monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_UNITS", "metric_mm")
    doc = FakeDoc(ENGINEERING)
    _collect(lambda: cad_engine.get_active_document(_app(doc)))
    assert doc.vars["INSUNITS"] == 4 and doc.vars["MEASUREMENT"] == 1 and doc.vars["LUNITS"] == 2


def test_invalid_units_policy_is_a_config_error(monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_UNITS", "furlongs")
    with pytest.raises(ConfigError) as info:
        cad_engine.get_active_document(_app(FakeDoc()))
    assert info.value.code == "E_INVALID_CONFIG"


def test_no_escape_when_no_command_is_active():
    doc = FakeDoc(ENGINEERING)
    cad_engine.get_active_document(_app(doc))
    assert doc.sent == []


def test_escape_sent_and_reported_when_a_command_is_active():
    doc = FakeDoc({**ENGINEERING, "CMDACTIVE": 1})
    _, notices = _collect(lambda: cad_engine.get_active_document(_app(doc)))
    assert doc.sent == ["\x1b\x1b"]
    assert {"kind": "pending_command_cancelled", "cmdactive": 1} in notices


def test_escape_still_sent_when_cmdactive_is_unreadable():
    # V0.2.x behaviour is kept when the document cannot report CMDACTIVE.
    sent = []
    doc = SimpleNamespace(SendCommand=sent.append, SetVariable=lambda *a: None)
    cad_engine.get_active_document(_app(doc))
    assert sent == ["\x1b\x1b"]


def test_pinned_session_refuses_another_drawing_before_touching_it():
    session.pin_document("path:c:\\projects\\a.dwg")
    doc = FakeDoc(METRIC, name="b.dwg", full_name="C:\\projects\\b.dwg")
    with pytest.raises(CadError) as info:
        cad_engine.get_active_document(_app(doc))
    assert info.value.code == "E_DOCUMENT_CHANGED"
    assert info.value.details == {
        "pinned_document": "path:c:\\projects\\a.dwg",
        "active_document": "path:c:\\projects\\b.dwg",
    }
    assert doc.set_calls == [] and doc.sent == []


def test_pinned_session_accepts_the_pinned_drawing():
    session.pin_document("path:c:\\projects\\a.dwg")
    doc = FakeDoc(ENGINEERING, name="a.dwg", full_name="C:\\Projects\\A.dwg")
    assert cad_engine.get_active_document(_app(doc)) is doc


def test_create_new_drawing_refuses_while_pinned_without_touching_autocad():
    session.pin_document("path:c:\\projects\\a.dwg")
    with patch("tools.primitives.get_connected_app", side_effect=AssertionError("must not reach COM")):
        with pytest.raises(CadError) as info:
            primitives.create_new_drawing()
    assert info.value.code == "E_DOCUMENT_PINNED"


def test_create_new_drawing_rejects_non_dwt_template_before_com():
    with patch("tools.primitives.get_connected_app", side_effect=AssertionError("must not reach COM")):
        with pytest.raises(CadError) as info:
            primitives.create_new_drawing(template="layout.dwg")
    assert info.value.code == "E_INVALID_INPUT"


def test_release_table_matches_reference_evidence():
    from utils.constants import RELEASE_TO_YEAR

    assert RELEASE_TO_YEAR[24.3] == 2024
    assert RELEASE_TO_YEAR[25.0] == 2025
    assert RELEASE_TO_YEAR[25.1] == 2026
    assert RELEASE_TO_YEAR[26.0] == 2027
    assert 24.4 not in RELEASE_TO_YEAR  # V0.2.x mapped this non-existent release to 2025 (D2)
