"""Tool registry, toolsets, annotations and the code-derived capability map."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import server
from backends.base import Backend
from backends.com import ComBackend
from backends.dxf import DxfBackend
from core import registry
from core.errors import ConfigError


def test_every_registered_mcp_tool_has_a_spec():
    names = {tool.name for tool in asyncio.run(server.server.list_tools())}
    assert names <= set(registry.specs())


def test_every_spec_operation_is_a_backend_operation():
    for spec in registry.specs().values():
        if spec.operation is not None:
            assert spec.operation in Backend.OPERATIONS, spec.name


def test_every_operation_used_by_a_tool_is_implemented_somewhere():
    implemented = registry.supported_operations(ComBackend) | registry.supported_operations(DxfBackend)
    for spec in registry.specs().values():
        if spec.operation is not None:
            assert spec.operation in implemented, f"{spec.name} calls {spec.operation}, which no backend implements"


def test_base_backend_refuses_every_operation():
    base = Backend()
    for operation in Backend.OPERATIONS:
        with pytest.raises(Exception) as info:
            getattr(base, operation)()
        assert getattr(info.value, "code", None) == "E_UNSUPPORTED_BACKEND"


def test_annotations_follow_kind():
    tools = {t.name: t for t in asyncio.run(server.server.list_tools())}
    for name, spec in registry.specs().items():
        if name not in tools:
            continue
        hints = tools[name].annotations
        read_only, destructive, idempotent = registry.KINDS[spec.kind]
        assert hints.read_only_hint is read_only, name
        assert hints.destructive_hint is destructive, name


def test_capability_map_lists_backends_per_tool():
    caps = registry.capability_map()
    assert caps["tools"]["autocad_draw_line"]["backends"][0] == "com"
    assert "launch_application" in caps["operations"]["com"]
    assert "launch_application" not in caps["operations"]["dxf"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("all", set(registry.TOOLSETS)),
        ("", set(registry.TOOLSETS)),
        ("drawing", {"core", "drawing"}),
        ("core, analysis ,output", {"core", "analysis", "output"}),
    ],
)
def test_enabled_toolsets(monkeypatch, raw, expected):
    monkeypatch.setenv("AUTOCAD_MCP_TOOLSETS", raw)
    assert registry.enabled_toolsets() == expected


def test_unknown_toolset_is_a_config_error(monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_TOOLSETS", "core,teleport")
    with pytest.raises(ConfigError):
        registry.enabled_toolsets()


def test_capabilities_tool_reports_config_and_backend():
    result = server.autocad_get_capabilities()
    assert result["backend"] == "com"
    assert result["server_version"]
    assert "autocad_get_capabilities" in result["tools"]
    assert result["config"]["units_preset"] == "engineering"
