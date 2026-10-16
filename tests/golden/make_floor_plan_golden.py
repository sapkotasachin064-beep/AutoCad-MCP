"""Regenerate tests/golden/floor_plan_v0_2_3.json from the ORIGINAL V0.2.3
implementation (git commit 3cf9254, src/tools/architectural.py), executed
against the recorded fake in tests/fakes.py.

The golden file is what V0.2.3 actually drew; test_floor_plan_parity.py
requires the V0.3.0 plan engine to draw exactly the same entities. Run from
the repository root:

    python tests/golden/make_floor_plan_golden.py
"""

import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fakes import FakeApp  # noqa: E402

BASELINE = "3cf9254"


def record(doc) -> list[dict]:
    rows = []
    for e in doc.ModelSpace._items:
        row = {"object_name": e.ObjectName, "layer": e.Layer}
        for prop in ("StartPoint", "EndPoint", "Coordinates", "Closed", "Center", "Radius", "StartAngle",
                     "EndAngle", "TextString", "InsertionPoint", "Width", "Height"):
            if hasattr(e, prop):
                value = getattr(e, prop)
                if isinstance(value, (tuple, list)):
                    value = [round(float(v), 6) for v in value]
                elif isinstance(value, float):
                    value = round(value, 6)
                row[prop] = value
        rows.append(row)
    return rows


def main():
    source = subprocess.run(["git", "show", f"{BASELINE}:src/tools/architectural.py"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    module = types.ModuleType("architectural_v0_2_3")
    exec(compile(source, "architectural_v0_2_3.py", "exec"), module.__dict__)
    cases = {}
    for name, kwargs in (("default_24x30", {}), ("36x40", {"width_ft": 36.0, "length_ft": 40.0})):
        app = FakeApp()
        module.get_connected_app = lambda app=app: app
        module.generate_2d_floor_plan(**kwargs)
        doc = app.ActiveDocument
        cases[name] = {"kwargs": kwargs, "entities": record(doc),
                       "layer_colors": {k: v.Color for k, v in doc.Layers._items.items()}}
    out = Path(__file__).with_name("floor_plan_v0_2_3.json")
    out.write_text(json.dumps({"source": f"git {BASELINE}:src/tools/architectural.py", "cases": cases}, indent=1),
                   encoding="utf-8")
    print(f"wrote {out}: " + ", ".join(f"{k}={len(v['entities'])} entities" for k, v in cases.items()))


if __name__ == "__main__":
    main()
