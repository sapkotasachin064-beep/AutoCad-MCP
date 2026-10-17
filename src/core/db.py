"""SQLite storage for scanned drawing entities.

The database is a cache of what scan_all_entities last saw, never the
authoritative source of a drawing: AutoCAD's own document is. Every drawing
is keyed by its identity.py identity string, so scanning one drawing never
touches another drawing's rows, and rescanning the same drawing replaces
only that drawing's entity snapshot (idempotent, no duplicate rows).
"""

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass

from core.errors import CadError, InvalidInputError

SCHEMA_VERSION = 1

_WRITE_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
    "ATTACH", "DETACH", "VACUUM", "PRAGMA", "BEGIN", "COMMIT", "ROLLBACK",
    "REINDEX", "ANALYZE",
)
_WRITE_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(_WRITE_KEYWORDS) + r")\b", re.IGNORECASE
)
_LEADING_COMMENT_RE = re.compile(r"\s*(--[^\n]*\n|/\*.*?\*/)\s*", re.DOTALL)


class QueryRejected(CadError, ValueError):
    """Raised when execute_query is asked to run something outside the
    read-only, single-statement scope this tool is approved for. Reaches the
    client as E_QUERY_REJECTED; still a ValueError, as in V0.2.x."""

    code = "E_QUERY_REJECTED"


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool = False


def _strip_leading_comments(sql: str) -> str:
    previous = None
    while previous != sql:
        previous = sql
        sql = _LEADING_COMMENT_RE.sub("", sql, count=1)
    return sql


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    # Autocommit mode: sqlite3's default isolation_level implicitly opens a
    # transaction before any DML statement, which collides with the explicit
    # BEGIN in replace_drawing_entities. Explicit BEGIN/COMMIT/ROLLBACK below
    # manage transactions instead.
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        return
    if current < 1:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS drawings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                path TEXT,
                saved INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_scanned_at TEXT
            );

            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drawing_id INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
                handle TEXT NOT NULL,
                object_name TEXT NOT NULL,
                layer TEXT,
                properties TEXT NOT NULL,
                scanned_at TEXT NOT NULL,
                UNIQUE(drawing_id, handle)
            );

            CREATE INDEX IF NOT EXISTS idx_entities_drawing_id ON entities(drawing_id);
            """
        )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


@contextmanager
def connection(db_path: str):
    conn = _connect(db_path)
    try:
        _migrate(conn)
        yield conn
    finally:
        conn.close()


def upsert_drawing(conn: sqlite3.Connection, identity: str, name: str, path: str | None, saved: bool) -> int:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        INSERT INTO drawings (identity, name, path, saved, first_seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(identity) DO UPDATE SET name = excluded.name, path = excluded.path, saved = excluded.saved
        """,
        (identity, name, path, int(saved), now),
    )
    row = conn.execute("SELECT id FROM drawings WHERE identity = ?", (identity,)).fetchone()
    return row[0]


def replace_drawing_entities(
    conn: sqlite3.Connection,
    drawing_id: int,
    entities: list[dict],
) -> int:
    """Atomically replace this drawing's entity snapshot. Other drawings'
    rows are untouched because the DELETE is scoped to drawing_id."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM entities WHERE drawing_id = ?", (drawing_id,))
        conn.executemany(
            """
            INSERT INTO entities (drawing_id, handle, object_name, layer, properties, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (drawing_id, e["handle"], e["object_name"], e.get("layer"), json.dumps(e["properties"]), now)
                for e in entities
            ],
        )
        conn.execute("UPDATE drawings SET last_scanned_at = ? WHERE id = ?", (now, drawing_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(entities)


def _validate_readonly_sql(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise QueryRejected("query must be a non-empty string")
    body = _strip_leading_comments(sql).strip()
    body = body.rstrip(";").strip()
    if ";" in body:
        raise QueryRejected("multiple statements are not allowed; submit exactly one SELECT")
    first_word_match = re.match(r"[A-Za-z]+", body)
    first_word = first_word_match.group(0).upper() if first_word_match else ""
    if first_word not in ("SELECT", "WITH"):
        raise QueryRejected(
            f"only read-only SELECT (optionally with a WITH clause) is allowed, got statement starting with {first_word!r}"
        )
    write_match = _WRITE_KEYWORD_RE.search(body)
    if write_match:
        raise QueryRejected(f"query contains disallowed keyword {write_match.group(0).upper()!r}")
    return body


def _schema_hint(conn: sqlite3.Connection) -> dict:
    """Table name -> column names, so a failed query can say what it may reference."""
    try:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: [col[1] for col in conn.execute(f'PRAGMA table_info("{name}")')] for name in names}
    except sqlite3.Error:
        return {}


def execute_readonly_query(
    db_path: str, sql: str, params: list | None = None, max_rows: int | None = None
) -> QueryResult:
    """Run a validated single-statement SELECT against a read-only connection.

    Two independent layers of enforcement: a keyword/shape check that gives a
    clear rejection message, and a connection opened with SQLite's own
    mode=ro URI flag, which refuses any write at the file level even if a
    query slips past the keyword check (e.g. a modern SQLite
    `WITH ... DELETE` CTE that lacks a SELECT keyword written out in full).

    max_rows (None = no limit, the V0.2.x behaviour) caps the rows returned;
    `truncated` says whether more rows matched.
    """
    statement = _validate_readonly_sql(sql)
    if not os.path.exists(db_path):
        return QueryResult(columns=[], rows=[], row_count=0)
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        cursor = conn.execute(statement, params or [])
        columns = [d[0] for d in cursor.description] if cursor.description else []
        if max_rows is None:
            fetched = cursor.fetchall()
            truncated = False
        else:
            fetched = cursor.fetchmany(max_rows + 1)
            truncated = len(fetched) > max_rows
            fetched = fetched[:max_rows]
        rows = [dict(zip(columns, row)) for row in fetched]
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)
    except sqlite3.OperationalError as exc:
        if "readonly" in str(exc).lower() or "read-only" in str(exc).lower():
            raise QueryRejected(f"query attempted a write and was rejected by the read-only connection: {exc}") from exc
        # A typo in the caller's own SELECT (unknown column or table, bad syntax) is theirs to fix: say so, and
        # show the schema, instead of letting it surface as an internal error.
        raise InvalidInputError(f"the query could not be run: {exc}", details={"tables": _schema_hint(conn)}) from exc
    except sqlite3.ProgrammingError as exc:  # e.g. wrong number of ? parameters
        raise InvalidInputError(f"the query could not be run: {exc}", details={"tables": _schema_hint(conn)}) from exc
    finally:
        conn.close()
