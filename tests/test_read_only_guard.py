"""Checks that the query tool refuses anything that isn't read-only.
Run:  python3 tests/test_read_only_guard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from metabase_query import QueryError, assert_read_only  # noqa: E402

ALLOWED = [
    "SELECT 1",
    "select * from user_outcome limit 5;",
    "WITH a AS (SELECT 1) SELECT * FROM a",
    "SHOW TABLES",
    "DESCRIBE hiring_request",
    "SELECT 'drop table x' AS note",  # keyword inside a string literal
    "SELECT 1 -- delete everything",  # keyword inside a comment
]
BLOCKED = [
    "DELETE FROM user_outcome",
    "UPDATE user_outcome SET x = 1",
    "INSERT INTO t VALUES (1)",
    "DROP TABLE t",
    "SELECT 1; DROP TABLE t",
    "SELECT * FROM t INTO OUTFILE '/tmp/x'",
    "/* hi */ TRUNCATE t",
    "",
]

failed = 0
for sql in ALLOWED:
    try:
        assert_read_only(sql)
    except QueryError as e:
        failed += 1
        print(f"FAIL (should allow): {sql!r} -> {e}")
for sql in BLOCKED:
    try:
        assert_read_only(sql)
        failed += 1
        print(f"FAIL (should block): {sql!r}")
    except QueryError:
        pass

print("All guard checks passed." if not failed else f"{failed} check(s) failed.")
sys.exit(1 if failed else 0)
