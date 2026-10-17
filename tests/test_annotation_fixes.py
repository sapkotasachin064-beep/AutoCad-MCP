"""Pure logic behind three annotation fixes: dimensions sized from a plot scale (DIMSCALE), inch and foot marks
kept clean in drawn text, and the layer a plan primitive must end up on. No AutoCAD, no ezdxf drawing."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backends.targets import dxf_dimension_override  # noqa: E402
from core.errors import CadError  # noqa: E402
from domain import units  # noqa: E402
from domain.architecture import Primitive  # noqa: E402
from utils import geometry  # noqa: E402

BS = "\\"  # one backslash, so no test below depends on how a Python literal escapes it


# ======= text with inch and foot marks =======


def test_inch_and_foot_marks_typed_normally_are_left_alone():
    text = "LIVING 12'-6\" x 10'-0\""
    assert geometry.clean_label_text(text) == text
    assert geometry.clean_label_text(text, multiline=True) == text


def test_a_backslash_in_front_of_a_quote_mark_is_dropped():
    sent = f"LIVING 12{BS}'-6{BS}\" x 10{BS}'-0{BS}\""
    assert geometry.clean_label_text(sent) == "LIVING 12'-6\" x 10'-0\""


def test_mtext_codes_and_escaped_backslashes_are_not_touched():
    for text in (f"BED{BS}PROOM", f"{BS}Fsimplex;{BS}S1/2;", f"C:{BS}{BS}plans", f"{BS}{BS}{BS}{BS}"):
        assert geometry.clean_label_text(text) == text
    # An escaped backslash followed by a plain quote keeps both; an escaped quote after the pair loses its backslash.
    assert geometry.clean_label_text(f"{BS}{BS}\"") == f"{BS}{BS}\""
    assert geometry.clean_label_text(f"{BS}{BS}{BS}\"") == f"{BS}{BS}\""


def test_real_line_breaks_become_mtext_paragraph_breaks_only_when_asked():
    assert geometry.clean_label_text("A\nB\r\nC\rD", multiline=True) == f"A{BS}PB{BS}PC{BS}PD"
    assert geometry.clean_label_text("A\nB") == "A\nB"  # single-line TEXT is not reshaped


def test_non_text_is_rejected_with_the_field_name():
    with pytest.raises(geometry.ValidationError, match="room name must be a string"):
        geometry.clean_label_text(12, "room name")


def test_cleaned_note_reports_the_original_only_when_it_changed():
    assert geometry.cleaned_note("a", "a") == {}
    assert geometry.cleaned_note(None, None) == {}
    assert geometry.cleaned_note(f"12{BS}\"", "12\"") == {"text_requested": f"12{BS}\""}


# ======= plot scale =======


def test_the_drawing_scale_must_be_a_positive_number_within_reason():
    assert units.validate_plot_scale(50) == 50.0 and units.validate_plot_scale(0.5) == 0.5
    for bad in (0, -1, True, "50", None, float("nan"), float("inf"), units.MAX_PLOT_SCALE * 2):
        with pytest.raises(CadError) as info:
            units.validate_plot_scale(bad)
        assert info.value.code == "E_INVALID_INPUT"


def test_scale_comes_from_the_caller_then_the_drawing_then_the_default():
    assert units.resolve_plot_scale(35, 100.0) == (35.0, "argument")
    assert units.resolve_plot_scale(None, 100.0) == (100.0, "drawing")
    assert units.resolve_plot_scale(None, 1.0) == (50.0, "default")  # AutoCAD's own default DIMSCALE is 1
    assert units.resolve_plot_scale(None, 0.0) == (50.0, "default")  # 0 = taken from the viewport: no scale to keep
    assert units.resolve_plot_scale(None, None) == (50.0, "default")
    assert units.resolve_plot_scale(1, 100.0) == (1.0, "argument")  # a 1:1 drawing can still be asked for


def test_dimension_sizes_are_paper_sizes_whose_product_with_the_scale_is_the_annotation_standard():
    mm = units.plot_scale_dimension(units.unit_code("mm"), 50)
    assert mm["dimscale"] == 50.0 and mm["text_height"] == pytest.approx(3.0) and mm["arrow"] == pytest.approx(3.0)
    assert mm["extension_beyond"] == pytest.approx(1.5) and mm["extension_offset"] == pytest.approx(0.75)
    assert mm["text_gap"] == pytest.approx(0.75) and mm["decimals"] == 0
    assert mm["drawn_text_height"] == pytest.approx(150.0)  # the same 150 mm every plan macro draws
    inch = units.plot_scale_dimension(units.unit_code("in"), 50)
    assert inch["text_height"] == pytest.approx(0.12) and inch["drawn_text_height"] == pytest.approx(6.0)
    assert inch["decimals"] == 2


def test_the_drawn_size_follows_the_scale_and_the_paper_size_does_not():
    at_35 = units.plot_scale_dimension(units.unit_code("mm"), 35)
    at_100 = units.plot_scale_dimension(units.unit_code("mm"), 100)
    assert at_35["text_height"] == at_100["text_height"] == pytest.approx(3.0)
    assert at_35["drawn_text_height"] == pytest.approx(105.0) and at_100["drawn_text_height"] == pytest.approx(300.0)
    metres = units.plot_scale_dimension(units.unit_code("m"), 50)
    assert metres["drawn_text_height"] == pytest.approx(0.15) and metres["decimals"] == 3


def test_units_without_a_fixed_length_cannot_be_sized():
    with pytest.raises(CadError) as info:
        units.plot_scale_dimension(0, 50)
    assert info.value.code == "E_UNITS_MISMATCH"


# ======= primitives and ezdxf overrides =======


def test_a_dimension_primitive_carries_its_dimscale_and_it_is_not_a_length_to_convert():
    from domain.architecture import Plan, scale_plan

    prim = Primitive("dim_linear", "A-DIM", "d", points=((0, 0, 0), (1, 0, 0)), location=(0, -1, 0), height=3.0,
                     dim_scale=50.0)
    assert prim.describe()["dim_scale"] == 50.0
    assert "dim_scale" not in Primitive("dim_linear", "A-DIM", "d").describe()
    plan = Plan()
    plan.add(prim)
    scale_plan(plan, 25.4)  # a unit conversion scales lengths, not the DIMSCALE ratio
    assert prim.height == pytest.approx(76.2) and prim.dim_scale == 50.0


def test_ezdxf_override_always_has_a_dimscale_when_it_sizes_the_text():
    plain = dxf_dimension_override(None)
    assert plain == {"dimlfac": 1.0}  # no height: the dimension keeps the style, only the x100 factor is fixed
    absolute = dxf_dimension_override(150.0, units.unit_code("mm"))
    assert absolute["dimscale"] == 1.0 and absolute["dimtxt"] == 150.0 and absolute["dimdec"] == 0
    scaled = dxf_dimension_override(3.0, units.unit_code("mm"), 50.0)
    assert scaled["dimscale"] == 50.0 and scaled["dimtxt"] == 3.0 and scaled["dimasz"] == 3.0
