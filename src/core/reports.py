"""Write QC / takeoff results to a file a person can file with a submission:
JSON (complete), CSV (one row per issue or per layer) or Markdown (readable
summary). The file is written to a temporary name and moved into place, and
its size and SHA-256 are read back from disk."""

import csv
import io
import json
import os
import uuid
from datetime import datetime, timezone

from core.evidence import file_evidence
from core.paths import output_path

FORMATS = {"json": ".json", "csv": ".csv", "md": ".md"}


def _qc_rows(result):
    return [{"rule": i.get("rule"), "severity": i.get("severity"), "handle": i.get("handle"), "layer": i.get("layer"),
             "type": i.get("type"), "message": i.get("message")} for i in result["issues"]]


def _takeoff_rows(result):
    rows = []
    for layer, data in result["layers"].items():
        row = {"layer": layer}
        for key, value in data.items():
            if isinstance(value, dict):
                for sub, v in value.items():
                    row[f"{key}.{sub}"] = json.dumps(v) if isinstance(v, dict) else v
            else:
                row[key] = value
        rows.append(row)
    return rows


def _markdown(kind, result, context):
    lines = [f"# {'Drawing check' if kind == 'qc' else 'Quantity takeoff'} report", "",
             f"- Drawing: `{context.get('drawing_identity')}`", f"- Backend: {context.get('backend')}",
             f"- Generated (UTC): {context['generated_utc']}", ""]
    if kind == "qc":
        lines += [f"**Result:** {'no errors' if result['passed'] else 'errors found'} -- "
                  f"{result['issue_count']} finding(s) over {result['entity_count']} entities.", "",
                  "| Rule | Findings | Meaning |", "|---|---|---|"]
        for rule, count in result["counts_by_rule"].items():
            lines.append(f"| {rule} | {count} | {result['rule_descriptions'][rule]} |")
        if result["issues"]:
            lines += ["", "| Severity | Rule | Handle | Layer | Message |", "|---|---|---|---|---|"]
            for i in result["issues"]:
                lines.append(f"| {i.get('severity')} | {i.get('rule')} | {i.get('handle') or ''} | {i.get('layer') or ''} | {i.get('message')} |")
    else:
        lines += [f"Drawing unit: {result['drawing_unit']}", "",
                  "| Layer | Entities | Line+polyline+arc length | Closed area | Hatch area | Blocks |",
                  "|---|---|---|---|---|---|"]
        for layer, d in result["layers"].items():
            length = d["line_length"] + d["open_polyline_length"] + d["arc_length"]
            lines.append(f"| {layer} | {d['entities']} | {length:.3f} | {d['closed_area']:.3f} | {d['hatch_area']:.3f} | "
                         f"{', '.join(f'{k} x{v}' for k, v in d['blocks'].items())} |")
    lines += ["", f"_{result['note']}_", ""]
    return "\n".join(lines)


def write_report(kind: str, result: dict, path: str, fmt: str, *, overwrite: bool, context: dict) -> dict:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {sorted(FORMATS)}")
    target = output_path(path, suffixes=(FORMATS[fmt],), overwrite=overwrite)
    context = {**context, "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if fmt == "json":
        text = json.dumps({"report": kind, "context": context, "result": result}, indent=1, default=str)
    elif fmt == "md":
        text = _markdown(kind, result, context)
    else:
        rows = _qc_rows(result) if kind == "qc" else _takeoff_rows(result)
        buffer = io.StringIO()
        fields = sorted({k for r in rows for k in r}, key=lambda k: (k != "layer" and k != "rule", k))
        writer = csv.DictWriter(buffer, fieldnames=fields or ["empty"])
        writer.writeheader()
        writer.writerows(rows)
        text = buffer.getvalue()
    temp = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}{target.suffix}")
    with open(temp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(temp, target)
    return file_evidence(target)
