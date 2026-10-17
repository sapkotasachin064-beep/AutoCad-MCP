"""Record the project's own live test run (tests/test_integration_autocad.py) as cases, and check the
files those tests left in pytest's temporary folder independently (PDF/DXF/DWG headers and sizes).
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
from cases import lib_case, record, sha256  # noqa: E402

JUNIT = h.EVIDENCE / "pytest-junit.xml"
TMP = h.RUN / "pytest-tmp"

root = ET.parse(JUNIT).getroot()
suite = root.find("testsuite") if root.tag == "testsuites" else root
for tc in suite.iter("testcase"):
    name = tc.get("name")
    failed = tc.find("failure") is not None or tc.find("error") is not None
    skipped = tc.find("skipped") is not None
    status = "FAIL" if failed else ("NOT_ATTEMPTED" if skipped else "PASS")
    record(id=f"PT-{name}", category="X", tool=None, title=f"project live test {name}", status=status, method="pytest",
           evidence=f"{tc.get('time')} s (tests/test_integration_autocad.py, real AutoCAD over COM, junit XML in evidence/)",
           problems=[] if status == "PASS" else ["see evidence/pytest-junit.xml"], log_ref="pytest-live-integration.txt")
    print(status, name, tc.get("time"))
print({k: suite.get(k) for k in ("tests", "failures", "errors", "skipped", "time")})


def check_pdf():
    pdf = TMP / "test_v030_export_and_plot_live0" / "sheet.pdf"
    data = pdf.read_bytes()
    assert data[:5] == b"%PDF-", f"header {data[:8]!r}"
    assert len(data) > 1000, f"size {len(data)}"
    assert b"%%EOF" in data[-1100:], "no %%EOF near the end"
    return f"{pdf.name}: {len(data)} bytes, header {data[:8]!r}, ends with %%EOF, sha256 {sha256(pdf)[:16]}..."


def check_dxf():
    dxf = TMP / "test_v030_export_and_plot_live0" / "copy.dxf"
    head = dxf.read_bytes()[:200]
    assert b"SECTION" in head, f"header {head[:60]!r}"
    import ezdxf
    doc = ezdxf.readfile(str(dxf))
    return f"{dxf.name}: {dxf.stat().st_size} bytes, ezdxf reads it (DXF version {doc.dxfversion}, {len(list(doc.modelspace()))} model-space entities)"


def check_dwg():
    dwg = TMP / "test_v030_save_as_then_close0" / "saved.dwg"
    head = dwg.read_bytes()[:6]
    assert head.startswith(b"AC10"), f"header {head!r}"
    assert dwg.stat().st_size > 1000, f"size {dwg.stat().st_size}"
    return f"{dwg.name}: {dwg.stat().st_size} bytes, header {head!r}"


lib_case("PTF-1", "P", "pytest output files", "PDF written by the project's live plot test is a real PDF (header, size, %%EOF)", check_pdf, method="pytest+file", tool_name="autocad_plot_pdf")
lib_case("PTF-2", "N", "pytest output files", "DXF written by the project's live export test is readable by ezdxf", check_dxf, method="pytest+file", tool_name="autocad_export_dxf")
lib_case("PTF-3", "B", "pytest output files", "DWG written by the project's live save-as test has a DWG header", check_dwg, method="pytest+file", tool_name="autocad_save_drawing")
