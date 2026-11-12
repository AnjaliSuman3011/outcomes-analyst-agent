"""Checks the read-only bridge's guards (no network). Run:  python3 tests/test_bridge_guard.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import os
os.environ.setdefault("BRIDGE_LOG_FILE", "/dev/null")
from readonly_bridge import Rejected, validate_select, with_timeout_hint, run_query, handle_rpc  # noqa: E402

ALLOWED = [
    "SELECT 1",
    "select * from hiring_request limit 5;",
    "WITH a AS (SELECT 1 AS x) SELECT * FROM a",
    "SELECT '#not a comment' AS a, '-- nor this' AS b",          # comment markers inside strings
    "SELECT 1 -- trailing comment",
    "SELECT /* inline */ COUNT(*) FROM hiring_request WHERE company_name NOT IN ('a','b')",
    "SELECT SUM(x='Sahil') AS manual FROM t WHERE CONVERT_TZ(createdon,'+00:00','+05:30')>='2026-10-01'",
    "SELECT it''s_fine FROM t".replace("it''s_fine", "'it''s fine' AS note"),
]
BLOCKED = [
    "",  "   ",
    "DELETE FROM hiring_request", "UPDATE hiring_request SET stage='x'", "INSERT INTO t VALUES (1)", "DROP TABLE t",
    "SELECT 1; DROP TABLE t", "SELECT 1; SELECT 2",
    "SHOW TABLES", "DESCRIBE hiring_request", "EXPLAIN SELECT 1",
    "SELECT SLEEP(5)", "SELECT sleep (5)", "SELECT SLEEP/**/(5)", "SELECT 1 UNION SELECT SLEEP(5)",
    "SELECT '#' , SLEEP(5)",                         # '#' inside a string must not hide the call
    "SELECT '--' , SLEEP(5)",
    "SELECT /*!50000 SLEEP(5) */ 1", "SELECT /*M!100000 SLEEP(5) */ 1",
    "SELECT BENCHMARK(100000000, MD5('a'))", "SELECT LOAD_FILE('/etc/passwd')", "SELECT GET_LOCK('a', 10)",
    "SELECT RELEASE_ALL_LOCKS()", "SELECT * FROM t INTO OUTFILE '/tmp/x'", "SELECT 1 INTO @x", "SELECT @@version",
    "SELECT @a := 1", "SELECT * FROM t FOR UPDATE", "SELECT * FROM t LOCK IN SHARE MODE",
    "SELECT 'a\\' , SLEEP(5), 'b'", "SELECT 'unterminated", "SELECT 1 /* unterminated",
    "SELECT {{x}} FROM t", "SELECT 1 [[ AND x ]]",
    "WITH a AS (SELECT 1) DELETE FROM t", "(SELECT 1)", "CALL foo()", "SET @a=1", "REPLACE INTO t VALUES (1)",
    "SELECT REPLACE(a,'b','c') FROM t",  # REPLACE is blocked outright (conservative)
]
failed = 0
for sql in ALLOWED:
    try:
        validate_select(sql)
    except Rejected as e:
        failed += 1; print(f"FAIL (should allow): {sql!r} -> {e}")
for sql in BLOCKED:
    try:
        validate_select(sql); failed += 1; print(f"FAIL (should block): {sql!r}")
    except Rejected:
        pass
# DB allow-list
for db in (437, 1, "x", None, 0):
    try:
        run_query(db, "SELECT 1"); failed += 1; print(f"FAIL (db {db!r} should be refused)")
    except Rejected:
        pass
# timeout hint only on plain SELECT
assert "MAX_EXECUTION_TIME(5000)" in with_timeout_hint("SELECT 1", 5000)
assert with_timeout_hint("WITH a AS (SELECT 1) SELECT * FROM a", 5000).startswith("WITH")
# MCP surface: exactly one tool, read-only
r = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {"client": "t"})
assert [t["name"] for t in r["result"]["tools"]] == ["run_readonly_sql"]
assert r["result"]["tools"][0]["annotations"]["readOnlyHint"] is True
r = handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "delete_rows", "arguments": {}}}, {"client": "t"})
assert "error" in r
r = handle_rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_readonly_sql", "arguments": {"db": 69, "sql": "DROP TABLE x"}}}, {"client": "t"})
assert r["result"]["isError"] is True
print("All bridge guard checks passed." if not failed else f"{failed} check(s) failed.")
sys.exit(1 if failed else 0)
