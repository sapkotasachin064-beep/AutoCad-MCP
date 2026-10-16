# Contributing

Thank you for helping. This project drives real drawings, so changes are
judged first on safety and honesty of results, then on features.

Before starting something large, open an issue describing the change. The
repository has no licence file yet; ask the maintainer how contributions
will be licensed before investing significant work.

## Set up

```powershell
git clone https://github.com/sapkotasachin064-beep/AutoCad-MCP.git
cd AutoCad-MCP
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dxf.txt pytest
python -m pytest tests -q
```

Without a running AutoCAD the live tests are skipped; everything else must
pass.

## Workflow

1. Create a branch from `main` (`feat/...`, `fix/...`, `docs/...`).
2. Make the change, following [AGENTS.md](AGENTS.md) (invariants and the
   "adding or changing a tool" checklist).
3. Add or update tests at the right layer (below).
4. Regenerate generated files when tools or capabilities change:
   `python scripts\build_tool_docs.py` and
   `python scripts\catalog\build_catalog.py`.
5. Add a line to `CHANGELOG.md` under the unreleased version. Behaviour
   changes also go in `docs/compatibility.md` with a migration note.
6. Run `python -m pytest tests -q` and paste the summary line in the pull
   request. If you ran the live tests, paste their output and the AutoCAD
   release.

## Test layers

| Layer | Use it for | File |
|---|---|---|
| Unit | validation, pure domain logic, errors, paths | `test_*.py` per module |
| Fake COM | what a COM tool sends and how it checks the result | `test_com_tools_fake.py` with `fakes.py` |
| Golden | output that must not drift (the V0.2.3 floor plan) | `test_floor_plan_parity.py` |
| Headless | real DXF files written and read back | `test_dxf_backend.py`, `test_workflow_headless_e2e.py` |
| stdio end-to-end | the server as a client sees it | `test_e2e_mcp.py` |
| Live | real AutoCAD round trips, skipped without AutoCAD | `test_integration_autocad.py` |

Rules:

* A fake-COM test is not a live test. Say which layer your evidence comes
  from.
* Do not skip, delete or weaken a failing test to make the suite pass.
* Live tests create their own scratch drawing and close it without saving;
  files go to pytest's temporary folder. Never use project drawings.
* Tests must not depend on the developer's AutoCAD profile, templates or
  printers beyond what `test_integration_autocad.py` documents.

## Style

* Match the surrounding code: plain functions, small modules, type hints on
  public functions, no new dependencies without discussion.
* Tool docstrings are what the model reads. State what the tool changes,
  units, defaults, limits and the dry-run behaviour in a few sentences.
* Raise `CadError` subclasses with a stable code; never return error
  dictionaries.
* Keep `src/domain/` free of pywin32 and ezdxf.

## Capability catalog

`scripts/catalog/data_*.py` lists capabilities with a status. Use
`planned` for ideas, `implemented` when code exists without a test, `tested`
when automated tests cover it, and `verified` only with recorded output from
a live AutoCAD run. Tests reject unknown tools and statuses that contradict
the evidence fields. To promote an entry, add it to
`scripts/catalog/data_live.py` with the live test that asserts it, and
record the run's output in `docs/testing.md`.

## Licensing of borrowed ideas

Do not copy code, tests or documentation from other repositories. You may
reimplement an idea from an MIT or Apache-2.0 project; credit it in the pull
request and in [docs/analysis/reuse-and-licensing.md](docs/analysis/reuse-and-licensing.md).
Nothing from GPL, AGPL, proprietary or unlicensed projects.

## Never commit

* drawings or data from real projects (`*.dwg` is ignored; check `*.dxf`
  before adding one as a fixture -- it must be synthetic),
* client configurations with personal paths or secrets,
* `.venv`, build output, caches, scan databases or plot output.
