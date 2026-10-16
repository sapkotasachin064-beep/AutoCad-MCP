import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db


def _entity(handle, object_name="AcDbLine", layer="0"):
    return {"handle": handle, "object_name": object_name, "layer": layer, "properties": {"n": handle}}


def test_migration_sets_schema_version(tmp_path):
    db_path = str(tmp_path / "test.db")
    with db.connection(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"drawings", "entities"} <= tables


def test_migration_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    with db.connection(db_path):
        pass
    with db.connection(db_path) as conn:  # second open must not error or duplicate schema
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_upsert_drawing_is_stable_across_calls(tmp_path):
    db_path = str(tmp_path / "test.db")
    with db.connection(db_path) as conn:
        id1 = db.upsert_drawing(conn, "path:c:/a.dwg", "a.dwg", "c:/a.dwg", True)
        id2 = db.upsert_drawing(conn, "path:c:/a.dwg", "a.dwg", "c:/a.dwg", True)
        conn.commit()
    assert id1 == id2


def test_rescanning_same_drawing_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    with db.connection(db_path) as conn:
        drawing_id = db.upsert_drawing(conn, "path:c:/a.dwg", "a.dwg", "c:/a.dwg", True)
        db.replace_drawing_entities(conn, drawing_id, [_entity("A1"), _entity("A2")])
        db.replace_drawing_entities(conn, drawing_id, [_entity("A1"), _entity("A2")])
        rows = conn.execute("SELECT handle FROM entities WHERE drawing_id = ? ORDER BY handle", (drawing_id,)).fetchall()
    assert [r[0] for r in rows] == ["A1", "A2"]


def test_rescan_drops_deleted_entities_but_keeps_others(tmp_path):
    db_path = str(tmp_path / "test.db")
    with db.connection(db_path) as conn:
        drawing_id = db.upsert_drawing(conn, "path:c:/a.dwg", "a.dwg", "c:/a.dwg", True)
        db.replace_drawing_entities(conn, drawing_id, [_entity("A1"), _entity("A2")])
        db.replace_drawing_entities(conn, drawing_id, [_entity("A1")])  # A2 was deleted in AutoCAD
        rows = conn.execute("SELECT handle FROM entities WHERE drawing_id = ?", (drawing_id,)).fetchall()
    assert [r[0] for r in rows] == ["A1"]


def test_scanning_isolates_different_drawings(tmp_path):
    db_path = str(tmp_path / "test.db")
    with db.connection(db_path) as conn:
        drawing_a = db.upsert_drawing(conn, "path:c:/a.dwg", "a.dwg", "c:/a.dwg", True)
        drawing_b = db.upsert_drawing(conn, "path:c:/b.dwg", "b.dwg", "c:/b.dwg", True)
        db.replace_drawing_entities(conn, drawing_a, [_entity("A1")])
        db.replace_drawing_entities(conn, drawing_b, [_entity("B1"), _entity("B2")])

        # Rescanning A must not touch B's rows.
        db.replace_drawing_entities(conn, drawing_a, [_entity("A1"), _entity("A3")])

        a_handles = {r[0] for r in conn.execute("SELECT handle FROM entities WHERE drawing_id = ?", (drawing_a,))}
        b_handles = {r[0] for r in conn.execute("SELECT handle FROM entities WHERE drawing_id = ?", (drawing_b,))}
    assert a_handles == {"A1", "A3"}
    assert b_handles == {"B1", "B2"}


def _seed(db_path, handles):
    with db.connection(db_path) as conn:
        drawing_id = db.upsert_drawing(conn, "path:c:/a.dwg", "a.dwg", "c:/a.dwg", True)
        db.replace_drawing_entities(conn, drawing_id, [_entity(h) for h in handles])


def test_execute_readonly_query_runs_select(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed(db_path, ["A1", "A2"])
    result = db.execute_readonly_query(db_path, "SELECT handle FROM entities ORDER BY handle")
    assert result.columns == ["handle"]
    assert [r["handle"] for r in result.rows] == ["A1", "A2"]


def test_execute_readonly_query_supports_parameters(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed(db_path, ["A1", "A2"])
    result = db.execute_readonly_query(db_path, "SELECT handle FROM entities WHERE handle = ?", ["A2"])
    assert [r["handle"] for r in result.rows] == ["A2"]


def test_execute_readonly_query_missing_db_returns_empty(tmp_path):
    db_path = str(tmp_path / "missing.db")
    result = db.execute_readonly_query(db_path, "SELECT 1")
    assert result.row_count == 0


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DELETE FROM entities",
        "DROP TABLE entities",
        "UPDATE entities SET handle = 'x'",
        "INSERT INTO entities (handle) VALUES ('x')",
        "PRAGMA table_info(entities)",
        "SELECT 1; DROP TABLE entities",
        "ATTACH DATABASE 'x' AS y",
        "",
        "   ",
    ],
)
def test_execute_readonly_query_rejects_unsafe_sql(tmp_path, bad_sql):
    db_path = str(tmp_path / "test.db")
    _seed(db_path, ["A1"])
    with pytest.raises(db.QueryRejected):
        db.execute_readonly_query(db_path, bad_sql)


def test_execute_readonly_query_rejects_cte_write_trick(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed(db_path, ["A1"])
    # SQLite's WITH-prefixed DELETE lacks a SELECT keyword; the write-keyword
    # check must still catch it even though the statement starts with WITH.
    sql = "WITH victims AS (SELECT id FROM entities) DELETE FROM entities WHERE id IN (SELECT id FROM victims)"
    with pytest.raises(db.QueryRejected):
        db.execute_readonly_query(db_path, sql)


def test_execute_readonly_query_allows_with_select(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed(db_path, ["A1", "A2"])
    sql = "WITH recent AS (SELECT handle FROM entities) SELECT handle FROM recent ORDER BY handle"
    result = db.execute_readonly_query(db_path, sql)
    assert [r["handle"] for r in result.rows] == ["A1", "A2"]
