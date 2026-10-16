"""Drawing creation and the single-line draw used by the V0.1.0 milestone."""

import os
from datetime import datetime

import pythoncom
import pywintypes
import win32com.client

from .config import get_output_dir
from .connection import com_initialized, get_connected_app, _retry_com

START_POINT = (0.0, 0.0, 0.0)
END_POINT = (100.0, 100.0, 0.0)


def _point_variant(point: tuple[float, float, float]):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, point)


def _unique_path(output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    while True:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        candidate = os.path.join(output_dir, f"mcp_test_{timestamp}.dwg")
        if not os.path.exists(candidate):
            return candidate


def create_test_drawing_with_line(output_dir: str | None = None) -> dict:
    with com_initialized():
        app = get_connected_app()
        output_dir = output_dir or get_output_dir()
        file_path = _unique_path(output_dir)

        try:
            doc = _retry_com(lambda: app.Documents.Add())
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create new drawing: {exc}") from exc

        active = _retry_com(lambda: app.ActiveDocument)
        if active.Name != doc.Name:
            raise RuntimeError(
                f"New drawing {doc.Name!r} was created but is not the active document "
                f"(active is {active.Name!r}); refusing to draw into the wrong drawing."
            )

        model_space = _retry_com(lambda: doc.ModelSpace)
        count_before = _retry_com(lambda: model_space.Count)

        try:
            line = _retry_com(
                lambda: model_space.AddLine(_point_variant(START_POINT), _point_variant(END_POINT))
            )
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to create line entity: {exc}") from exc

        count_after = _retry_com(lambda: model_space.Count)
        if count_after != count_before + 1 or line.ObjectName != "AcDbLine":
            raise RuntimeError("Line entity was not created as expected in ModelSpace.")

        if os.path.exists(file_path):
            raise RuntimeError(f"Refusing to overwrite existing file: {file_path}")

        try:
            _retry_com(lambda: doc.SaveAs(file_path))
        except pywintypes.com_error as exc:
            raise RuntimeError(f"Failed to save drawing to {file_path}: {exc}") from exc

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise RuntimeError(f"Save reported success but file is missing or empty: {file_path}")

        return {
            "status": "ok",
            "file_path": file_path,
            "line_handle": line.Handle,
            "start_point": START_POINT,
            "end_point": END_POINT,
            "message": f"Drawing saved with 1 line entity at {file_path}",
        }
