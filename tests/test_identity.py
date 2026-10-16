import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cad_engine import get_drawing_identity


def test_saved_document_identity_uses_path():
    doc = SimpleNamespace(Name="a.dwg", Path="C:\\drawings", FullName="C:\\drawings\\a.dwg")
    identity = get_drawing_identity(doc)
    assert identity.saved is True
    assert identity.path == "C:\\drawings\\a.dwg"
    assert identity.identity == "path:c:\\drawings\\a.dwg"


def test_unsaved_document_identity_has_no_path():
    # Verified against a live AutoCAD 2024: a brand-new unsaved document has
    # doc.Path set to the process's current working directory (non-empty!)
    # and doc.FullName == "". FullName, not Path, is the saved/unsaved signal.
    doc = SimpleNamespace(Name="Drawing1.dwg", Path="C:\\WINDOWS\\system32", FullName="")
    identity = get_drawing_identity(doc)
    assert identity.saved is False
    assert identity.path is None
    assert identity.identity == "unsaved:drawing1.dwg"


def test_identity_is_case_insensitive_for_same_saved_path():
    doc_lower = SimpleNamespace(Name="a.dwg", Path="c:\\drawings", FullName="c:\\drawings\\a.dwg")
    doc_upper = SimpleNamespace(Name="A.DWG", Path="C:\\DRAWINGS", FullName="C:\\DRAWINGS\\A.DWG")
    assert get_drawing_identity(doc_lower).identity == get_drawing_identity(doc_upper).identity
