#!/usr/bin/env python3
"""Read-only SQL runner for the Outcomes Analyst, via Metabase session login.

Usage:
    python3 tools/metabase_query.py "SELECT 1"
    python3 tools/metabase_query.py --json "SELECT 1 AS ok"
    python3 tools/metabase_query.py --db 434 "SELECT 1"     # LSQ database
    python3 tools/metabase_query.py --db 437 "SELECT 1"     # LSQ Career Services database

Databases: 69 = sql-prod-new (MySQL read replica, default via METABASE_DB_ID),
434 = LSQ (leads), 437 = LSQ Career Services (CS referral data). Any other id is rejected.

Flow: POST /api/session (user + password) -> token, then POST /api/dataset with that
token against METABASE_DB_ID. On a 401 the tool logs in again once and retries.
Only SELECT / WITH / SHOW / DESCRIBE / EXPLAIN statements are allowed (MySQL dialect).
Credentials come from the environment or the project's .env file; never hardcode them.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 120

ALLOWED_DBS = (69, 434, 437)
ALLOWED_START = ("select", "with", "show", "describe", "desc", "explain")
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
    r"rename|call|load|handler|lock|unlock|set|into\s+(outfile|dumpfile))\b",
    re.IGNORECASE,
)


class QueryError(Exception):
    pass


def load_env():
    """Read KEY=VALUE lines from .env without overriding real environment variables."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _strip_sql(sql):
    """Remove comments and string literals so the guard only sees SQL keywords."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"(--|#)[^\n]*", " ", sql)
    sql = re.sub(r"'(?:[^'\\]|\\.|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"\\]|\\.|"")*"', '""', sql)
    return sql.strip()


def assert_read_only(sql):
    body = _strip_sql(sql).rstrip(";").strip()
    if not body:
        raise QueryError("Empty query.")
    if ";" in body:
        raise QueryError("Only one statement per call is allowed.")
    if not body.lower().startswith(ALLOWED_START):
        raise QueryError("Blocked: only SELECT-style (read-only) queries are allowed.")
    match = FORBIDDEN.search(body)
    if match:
        raise QueryError(f"Blocked: '{match.group(0)}' is not allowed in a read-only query.")


def _post(url, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Metabase-Session"] = token
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise QueryError(f"HTTP {e.code} from {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise QueryError(f"Network error reaching {url}: {e.reason}") from e


class Metabase:
    def __init__(self, db_id=None):
        load_env()
        missing = [
            k
            for k in ("METABASE_URL", "METABASE_USER", "METABASE_PASSWORD", "METABASE_DB_ID")
            if not os.environ.get(k)
        ]
        if missing:
            raise QueryError(f"Missing in .env: {', '.join(missing)}")
        self.url = os.environ["METABASE_URL"].rstrip("/")
        self.user = os.environ["METABASE_USER"]
        self.password = os.environ["METABASE_PASSWORD"]
        self.db_id = int(db_id if db_id is not None else os.environ["METABASE_DB_ID"])
        if self.db_id not in ALLOWED_DBS:
            raise QueryError(f"Database {self.db_id} is not allowed; use one of {ALLOWED_DBS}.")
        self.token = None

    def login(self):
        data = _post(
            f"{self.url}/api/session", {"username": self.user, "password": self.password}
        )
        self.token = data.get("id")
        if not self.token:
            raise QueryError("Login succeeded but no session token was returned.")

    def query(self, sql):
        """Run a read-only SQL query; returns (columns, rows)."""
        assert_read_only(sql)
        payload = {
            "database": self.db_id,
            "type": "native",
            "native": {"query": sql},
        }
        if not self.token:
            self.login()
        try:
            result = _post(f"{self.url}/api/dataset", payload, self.token)
        except QueryError as e:
            if "HTTP 401" not in str(e):
                raise
            self.login()  # token expired: log in once more and retry
            result = _post(f"{self.url}/api/dataset", payload, self.token)
        # Metabase returns HTTP 202 with status=failed for SQL errors
        if result.get("error") or result.get("status") == "failed":
            raise QueryError(f"Query failed: {result.get('error') or result}")
        data = result["data"]
        columns = [c["name"] for c in data["cols"]]
        return columns, data["rows"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sql", help="A single read-only MySQL query")
    parser.add_argument(
        "--db", type=int, choices=ALLOWED_DBS, default=None,
        help="Metabase database id (default: METABASE_DB_ID from .env, i.e. 69)",
    )
    parser.add_argument("--json", action="store_true", help="Print rows as JSON")
    args = parser.parse_args()
    try:
        columns, rows = Metabase(args.db).query(args.sql)
    except QueryError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(json.dumps([dict(zip(columns, r)) for r in rows], default=str, indent=2))
    else:
        print("\t".join(columns))
        for r in rows:
            print("\t".join("" if v is None else str(v) for v in r))
        print(f"({len(rows)} rows)", file=sys.stderr)


if __name__ == "__main__":
    main()
