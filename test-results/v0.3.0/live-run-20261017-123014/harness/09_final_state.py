"""Step 9 - final state: exact AutoCAD release strings, drawings left open, src/ and tests/ unchanged, every PDF
re-verified by header and size, and the evidence about the failed cold start (crash report), collected read-only.
"""

import hashlib
import json
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402
from cases import record  # noqa: E402

EV = h.EVIDENCE
REPO = h.REPO


def manifest(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            out[str(p.relative_to(REPO)).replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def git(*args) -> str:
    return subprocess.run(["git", "--no-optional-locks", "-C", str(REPO), *args], capture_output=True, text=True, timeout=60).stdout.strip()


def main():
    # ---------------------------------------------------------------- release strings (needs one scratch drawing for the system variables)
    base = cp.baseline()
    app = cp.app()
    info = {"acad_exe_pids": cp.acad_pids(), "drawings_open_before_probe": base}
    doc = cp.retry(lambda: app.Documents.Add())
    try:
        info.update(cp.acad_info())
        info["ACADVER"] = cp.sysvar(doc, "ACADVER")
    finally:
        cp.close_new_docs(base)
    info["drawings_open_after_probe"] = cp.doc_list()
    h.dump(EV / "autocad_release_final.json", info)
    print("Application.Version:", info.get("Application.Version"), "| ACADVER:", info.get("ACADVER"), "| _VERNUM:", info.get("var._VERNUM"), "| PRODUCT:", info.get("var.PRODUCT"), "| RELEASE:", info.get("var.RELEASE"))
    print("AutoCAD pids:", info["acad_exe_pids"], "| drawings open now:", info["drawings_open_after_probe"])

    # ---------------------------------------------------------------- src/ and tests/ untouched
    before = json.loads((EV / "src_tests_manifest_before.json").read_text(encoding="utf-8"))
    after = {"src": manifest(REPO / "src"), "tests": manifest(REPO / "tests")}
    h.dump(EV / "src_tests_manifest_after.json", after)
    changed = {k: (before[k].get(f), after[k].get(f)) for k in ("src", "tests") for f in sorted(set(before[k]) | set(after[k])) if before[k].get(f) != after[k].get(f)}
    status_after = git("status", "--short")
    (EV / "git_status_after.txt").write_text(status_after + "\n\n" + git("diff", "--stat") + "\n", encoding="utf-8")
    status_before = (EV / "git_status_before.txt").read_text(encoding="utf-8").split("\n\n")[0].strip()
    same_status = status_before == status_after.strip()
    record(id="ENV01", category="X", tool=None, title="src/ and tests/ are byte-identical before and after the campaign; git status unchanged; nothing committed or pushed",
           status="PASS" if not changed and same_status else "FAIL", method="direct-library",
           evidence=f"{sum(len(v) for v in before.values())} files hashed before and after; changed files: {changed or 'none'}; git status identical: {same_status}",
           problems=[] if not changed and same_status else [str(changed) or "git status changed"], log_ref="evidence/src_tests_manifest_*.json")
    print("src/tests changed:", changed or "none", "| git status identical:", same_status)

    # ---------------------------------------------------------------- every PDF: header, size, pages
    import pdfplumber

    rows = []
    for pdf in sorted(list((h.WORKSPACE).rglob("*.pdf")) + list((h.RUN / "pytest-tmp").rglob("*.pdf"))):
        data = pdf.read_bytes()
        try:
            with pdfplumber.open(str(pdf)) as f:
                pages = len(f.pages)
                mm = [round(f.pages[0].width * 25.4 / 72, 1), round(f.pages[0].height * 25.4 / 72, 1)]
        except Exception as exc:
            pages, mm = None, repr(exc)[:80]
        rows.append({"file": str(pdf.relative_to(h.RUN)).replace("\\", "/"), "size_bytes": len(data), "header": data[:8].decode("latin1"), "header_ok": data[:5] == b"%PDF-",
                     "ends_with_eof": b"%%EOF" in data[-2048:], "pages": pages, "page_mm": mm, "sha256": hashlib.sha256(data).hexdigest()})
    h.dump(EV / "pdf-verification.json", rows)
    ok = all(r["header_ok"] and r["ends_with_eof"] and r["size_bytes"] > 1000 and r["pages"] == 1 for r in rows)
    record(id="ENV02", category="P", tool="autocad_plot_pdf", title="every PDF written in this campaign is a real one-page PDF (header %PDF-, ends with %%EOF, size > 1 kB)",
           status="PASS" if ok and rows else "FAIL", method="file", evidence=f"{len(rows)} PDFs: " + "; ".join(f"{Path(r['file']).name} {r['size_bytes']} B {r['page_mm']} mm" for r in rows),
           problems=[] if ok else ["see evidence/pdf-verification.json"], log_ref="evidence/pdf-verification.json")
    print(f"{len(rows)} PDFs verified; all fine: {ok}")

    # ---------------------------------------------------------------- evidence about the failed cold start (read-only copies / parsed facts, no personal fields)
    crash_dir = EV / "launch-crash"
    crash_dir.mkdir(exist_ok=True)
    cer_root = Path.home() / "AppData" / "Local" / "Autodesk" / "CER"
    facts = {"note": "collected after the first, tool-started AutoCAD launch failed (logs/01_launch.*); AutoCAD's own crash reporter output"}
    logs = sorted(cer_root.rglob("cer.log")) if cer_root.exists() else []
    if logs:
        shutil.copyfile(logs[-1], crash_dir / "cer.log")
        facts["cer_log_copied"] = True
    dumps = sorted(cer_root.rglob("acminidump.dmp")) if cer_root.exists() else []
    if dumps:
        d = dumps[0].read_bytes()
        sig, ver, ns, dir_rva, csum, ts, flags = struct.unpack_from("<4sIIIIIQ", d, 0)
        streams = {}
        for i in range(ns):
            t, size, rva = struct.unpack_from("<III", d, dir_rva + 12 * i)
            streams.setdefault(t, []).append((size, rva))
        if 6 in streams:
            size, rva = streams[6][0]
            tid, _ = struct.unpack_from("<II", d, rva)
            code, fl, rec, addr, nparams = struct.unpack_from("<IIQQI", d, rva + 8)
            params = struct.unpack_from("<15Q", d, rva + 8 + 4 + 4 + 8 + 8 + 4 + 4)
            facts["minidump"] = {"file": str(dumps[0].relative_to(Path.home())).replace("\\", "/"), "dump_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                                 "exception_code": f"0x{code:08X}", "meaning": "0xE0434352 = a .NET (CLR) exception thrown inside AutoCAD; first parameter 0x80131534 = TypeInitializationException",
                                 "exception_parameters": [hex(x) for x in params[:nparams]]}
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "Get-WinEvent -FilterHashtable @{LogName='System'; Id=10010; StartTime=(Get-Date).AddHours(-3)} -ErrorAction SilentlyContinue | Select-Object -First 3 TimeCreated, ProviderName, Id, Message | ConvertTo-Json -Compress"],
                        capture_output=True, text=True, timeout=60).stdout.strip()
    facts["dcom_event_10010"] = json.loads(ps) if ps else None
    h.dump(crash_dir / "launch-crash-facts.json", facts)
    print("crash facts:", json.dumps(facts, ensure_ascii=False)[:600])


main()
