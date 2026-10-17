"""Opening the index database read-only from a path a URI would otherwise cut.

Kept apart from test_rejoin.py, which the frozen-build smoke test imports without
pytest installed.
"""

import os
import sqlite3
from pathlib import Path

import pytest

import exoprobe
from test_rejoin import _meta

INDEX_TABLES = {"3f2a": {1: {"key": "https://x.example/a.mp4", "length": 5}}}


def _index_db(folder: Path) -> Path:
    folder.mkdir()
    db = folder / exoprobe.DB_NAME
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE "ExoPlayerCacheIndex3f2a" (id INTEGER PRIMARY KEY, key TEXT, metadata BLOB)')
    con.execute('INSERT INTO "ExoPlayerCacheIndex3f2a" VALUES (1, ?, ?)', ("https://x.example/a.mp4", _meta(5)))
    con.commit()
    con.close()
    return db


def test_a_folder_name_with_hash_or_question_mark_does_not_cut_the_path(tmp_path):
    # Unquoted, the URI ends at the '#', so SQLite opens (and creates) "case " instead.
    # Windows forbids '?' in a name, so there a '%3F' checks the quoting of '%'.
    name = "case #1 %3F" if os.name == "nt" else "case #1?x"
    db = _index_db(tmp_path / name)
    assert exoprobe.read_index_tables(db) == INDEX_TABLES
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


@pytest.mark.skipif(os.name != "nt", reason="UNC paths are Windows only")
def test_a_unc_path_is_opened(tmp_path):
    drive, rest = os.path.splitdrive(str(tmp_path))
    unc = Path(rf"\\localhost\{drive[0]}$" + rest)
    if not unc.is_dir():
        pytest.skip(f"the administrative share for {drive} is not reachable")
    db = _index_db(unc / "case #2")
    assert exoprobe.read_index_tables(db) == INDEX_TABLES
