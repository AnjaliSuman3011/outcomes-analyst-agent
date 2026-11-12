#!/usr/bin/env python3
"""Read-only front-door bridge for the Outcomes Analyst (stdlib only).

Speaks MCP "Streamable HTTP" (JSON-RPC 2.0 over POST /mcp) so a Claude Project custom connector can attach to it,
and also offers a plain  POST /query  endpoint with the same guards (for curl / a custom GPT Action).

ONE capability: run a SELECT against Metabase DB 69 or 434. There is no write path in this file.
Guards (all enforced in code, before anything reaches Metabase):
  * bearer token required on EVERY request (constant-time compare); the server refuses to start without one
  * only DB 69 / 434; only SELECT or WITH...SELECT; one statement; no executable comments; no Metabase {{ }} / [[ ]] templating
  * a real tokenizer strips strings and comments before checks (a '#' or '--' inside a string cannot hide code)
  * forbidden write keywords, INTO, '@' variables, and a function deny-list (SLEEP, BENCHMARK, LOAD_FILE, locks ...)
  * row cap (rows beyond it are dropped and flagged), statement timeout (MySQL MAX_EXECUTION_TIME hint + client timeout)
  * structured JSON logging of every request, allowed or denied (the token and credentials are never logged)
Credentials (METABASE_*) and BRIDGE_TOKEN come from the environment / git-ignored .env only. Binds to 127.0.0.1.

Run:  export BRIDGE_TOKEN=$(openssl rand -hex 24) && python3 tools/readonly_bridge.py
"""
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metabase_query as mq  # noqa: E402  (reused: Metabase login/query client + env loader)

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_DBS = (69, 434)
MAX_SQL_CHARS = 20_000
MAX_BODY_BYTES = 64 * 1024
IST = timezone(timedelta(hours=5, minutes=30))
SERVER_INFO = {"name": "outcomes-analyst-readonly-bridge", "version": "1.0.0"}
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

# Functions that block, sleep, read files, take locks or otherwise have side effects.
DENY_FUNCS = (
    "sleep", "benchmark", "load_file", "get_lock", "release_lock", "release_all_locks", "is_free_lock",
    "is_used_lock", "master_pos_wait", "source_pos_wait", "wait_for_executed_gtid_set",
    "wait_until_sql_thread_after_gtids", "sys_exec", "sys_eval", "pg_sleep", "load_data", "uuid_short",
    "named_lock", "set_var", "gtid_subtract", "row_count_of_write",
)
_DENY_RE = re.compile(r"\b(" + "|".join(DENY_FUNCS) + r")\b\s*\(", re.IGNORECASE)
_WRITE_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|rename|call|load|handler|lock|"
    r"unlock|set|into|outfile|dumpfile|do|prepare|execute|deallocate|savepoint|rollback|commit|start|begin|"
    r"flush|reset|kill|install|uninstall|optimize|repair|analyze|import|use|purge|shutdown|clone|restart)\b",
    re.IGNORECASE,
)


class Rejected(Exception):
    """The request was refused by a guard (never reaches Metabase)."""


def _sanitize(sql):
    """Tokenize: replace string literals with '' and comments with a space. Rejects anything ambiguous."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == "\\":
                    raise Rejected("Backslashes inside string literals are not allowed.")
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:  # doubled quote escape
                        j += 2
                        continue
                    break
                j += 1
            else:
                raise Rejected("Unterminated string literal.")
            out.append("''")
            i = j + 1
        elif c == "`":
            j = sql.find("`", i + 1)
            if j == -1:
                raise Rejected("Unterminated backtick identifier.")
            out.append("`x`")
            i = j + 1
        elif sql.startswith("/*", i):
            if sql.startswith("/*!", i) or sql.startswith("/*M!", i):
                raise Rejected("MySQL executable comments (/*! ... */) are not allowed.")
            j = sql.find("*/", i + 2)
            if j == -1:
                raise Rejected("Unterminated block comment.")
            out.append(" ")
            i = j + 2
        elif c == "#" or (sql.startswith("--", i) and (i + 2 >= n or sql[i + 2] in " \t\r\n")):
            j = sql.find("\n", i)
            out.append(" ")
            i = n if j == -1 else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def validate_select(sql):
    """Return the sanitized body if `sql` is a single plain SELECT / WITH...SELECT, else raise Rejected."""
    if not isinstance(sql, str) or not sql.strip():
        raise Rejected("Empty query.")
    if len(sql) > MAX_SQL_CHARS:
        raise Rejected(f"Query too long (max {MAX_SQL_CHARS} characters).")
    if "\x00" in sql:
        raise Rejected("NUL byte in query.")
    if "{{" in sql or "[[" in sql:
        raise Rejected("Metabase template tags ({{ }} / [[ ]]) are not allowed.")
    body = _sanitize(sql).strip()
    body = body.rstrip(";").strip()
    if not body:
        raise Rejected("Empty query.")
    if ";" in body:
        raise Rejected("Only one statement per call is allowed.")
    if "@" in body:
        raise Rejected("User/system variables (@) are not allowed.")
    if not re.match(r"(?is)^(select|with)\b", body):
        raise Rejected("Blocked: only SELECT (or WITH ... SELECT) queries are allowed.")
    m = _WRITE_RE.search(body)
    if m:
        raise Rejected(f"Blocked keyword: {m.group(0).upper()}.")
    m = _DENY_RE.search(body)
    if m:
        raise Rejected(f"Blocked function: {m.group(1).upper()}().")
    return body


def with_timeout_hint(sql, ms):
    """For a plain SELECT, ask MySQL itself to stop after `ms` (server-side statement timeout)."""
    if re.match(r"(?is)^\s*select\b", sql):
        return re.sub(r"(?is)^(\s*select\b)", rf"\1 /*+ MAX_EXECUTION_TIME({int(ms)}) */", sql, count=1)
    return sql


# ---------------------------------------------------------------- runtime config / state
mq.load_env()
CFG = {
    "max_rows": int(os.environ.get("BRIDGE_MAX_ROWS", "500")),
    "timeout_s": int(os.environ.get("BRIDGE_TIMEOUT_S", "60")),
    "rate_per_min": int(os.environ.get("BRIDGE_RATE_PER_MIN", "60")),
    "allow_url_token": os.environ.get("BRIDGE_ALLOW_URL_TOKEN", "") == "1",
    "log_file": os.environ.get("BRIDGE_LOG_FILE", str(ROOT / "logs" / "bridge.log")),
}
_clients, _client_lock = {}, threading.Lock()
_query_sem = threading.Semaphore(3)
_rate_lock, _rate_hits = threading.Lock(), []
_log_lock = threading.Lock()


def log(event, **fields):
    rec = {"ts": datetime.now(IST).isoformat(timespec="milliseconds"), "event": event, **fields}
    line = json.dumps(rec, default=str)
    with _log_lock:
        print(line, flush=True)
        try:
            Path(CFG["log_file"]).parent.mkdir(parents=True, exist_ok=True)
            with open(CFG["log_file"], "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def rate_ok():
    now = time.time()
    with _rate_lock:
        _rate_hits[:] = [t for t in _rate_hits if now - t < 60]
        if len(_rate_hits) >= CFG["rate_per_min"]:
            return False
        _rate_hits.append(now)
        return True


def get_client(db):
    with _client_lock:
        if db not in _clients:
            _clients[db] = mq.Metabase(db)
        return _clients[db]


def run_query(db, sql):
    """Validate, run, cap. Returns a dict. Raises Rejected / mq.QueryError."""
    try:
        db = int(db)
    except (TypeError, ValueError):
        raise Rejected("db must be 69 or 434.")
    if db not in ALLOWED_DBS:
        raise Rejected(f"Database {db} is not allowed; use one of {ALLOWED_DBS}.")
    validate_select(sql)
    mq.assert_read_only(sql)  # second, independent guard (the repo's original tool)
    sent = with_timeout_hint(sql, CFG["timeout_s"] * 1000)
    mq.TIMEOUT = CFG["timeout_s"]
    if not _query_sem.acquire(timeout=5):
        raise Rejected("Too many concurrent queries; retry shortly.")
    try:
        t0 = time.time()
        client = get_client(db)
        columns, rows = client.query(sent)
        ms = int((time.time() - t0) * 1000)
    finally:
        _query_sem.release()
    total = len(rows)
    truncated = total > CFG["max_rows"]
    return {
        "db": db,
        "sql": sql,
        "as_of_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "row_count": total,
        "returned_rows": min(total, CFG["max_rows"]),
        "truncated": truncated,
        "columns": columns,
        "rows": rows[: CFG["max_rows"]],
        "elapsed_ms": ms,
    }


TOOL = {
    "name": "run_readonly_sql",
    "description": (
        "Run ONE read-only SELECT (or WITH...SELECT) against Crio's Metabase replicas. db=69 is production "
        "(hiring_request, user_hiring_round, user_outcome); db=434 is LeadSquared (ProspectActivity_ExtensionBase, "
        "ProspectActivityEntityAudit_Base, Users). Times are stored in UTC: convert with CONVERT_TZ(x,'+00:00','+05:30'). "
        "Aggregate in SQL (GROUP BY); results are capped. Writes, multiple statements, SLEEP/BENCHMARK/locks, INTO, "
        "variables and comments-with-code are rejected. Returns the SQL, an as-of timestamp (IST), columns and rows."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "db": {"type": "integer", "enum": list(ALLOWED_DBS), "description": "Metabase database id: 69 or 434"},
            "sql": {"type": "string", "description": "A single SELECT or WITH...SELECT statement (MySQL dialect)"},
        },
        "required": ["db", "sql"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
}


def _text_result(obj, is_error=False):
    return {"content": [{"type": "text", "text": json.dumps(obj, default=str)}], "isError": is_error}


def handle_rpc(msg, ctx):
    """Handle one JSON-RPC message. Returns a response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    is_note = "id" not in msg
    if method == "initialize":
        want = params.get("protocolVersion")
        ver = want if want in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
            "instructions": "Read-only access to Crio Outcomes data. Use run_readonly_sql with db 69 or 434. Always show the SQL and as-of time.",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool"}}
        args = params.get("arguments") or {}
        return {"jsonrpc": "2.0", "id": mid, "result": execute_logged(args.get("db"), args.get("sql"), ctx, "mcp")}
    if is_note:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def execute_logged(db, sql, ctx, via):
    """Run a query, log it, and return an MCP tool result (errors become isError results, not crashes)."""
    h = hashlib.sha256(str(sql).encode()).hexdigest()[:12]
    base = {"via": via, "client": ctx["client"], "db": db, "sql": sql, "sql_sha": h}
    if not rate_ok():
        log("query_denied", reason="rate_limited", **base)
        return _text_result({"error": "Rate limit exceeded; retry in a minute."}, True)
    try:
        res = run_query(db, sql)
    except Rejected as e:
        log("query_denied", reason=str(e), **base)
        return _text_result({"error": f"Rejected by read-only guard: {e}", "sql": sql}, True)
    except mq.QueryError as e:
        log("query_error", error=str(e)[:300], **base)
        return _text_result({"error": f"Query failed: {e}", "sql": sql}, True)
    except Exception as e:  # never leak a stack trace to the caller
        log("query_error", error=f"{type(e).__name__}: {e}"[:300], **base)
        return _text_result({"error": "Internal error running the query.", "sql": sql}, True)
    log("query_ok", row_count=res["row_count"], truncated=res["truncated"], elapsed_ms=res["elapsed_ms"], **base)
    return _text_result(res)


class Handler(BaseHTTPRequestHandler):
    server_version = "OutcomesBridge/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence default access log; we log structured events instead
        pass

    def _send(self, code, obj=None, extra=None):
        body = b"" if obj is None else json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authorized(self):
        """Returns (ok, route_path). Bearer header always accepted; URL token only if explicitly enabled."""
        token = self.server.token
        path = self.path.split("?", 1)[0]
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip().encode(), token.encode()):
            return True, path
        if CFG["allow_url_token"]:
            m = re.match(r"^/t/([^/]+)(/.*)$", path)
            if m and hmac.compare_digest(m.group(1).encode(), token.encode()):
                return True, m.group(2)
        return False, path

    def _client_ip(self):
        return self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For") or self.client_address[0]

    def _guard(self):
        ok, route = self._authorized()
        ctx = {"client": self._client_ip()}
        if not ok:
            log("auth_denied", client=ctx["client"], method=self.command, path=re.sub(r"/t/[^/]+", "/t/<redacted>", self.path)[:80])
            self._send(401, {"error": "Unauthorized"}, {"WWW-Authenticate": 'Bearer realm="outcomes-analyst"'})
            return None, None
        return route, ctx

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY_BYTES:
            self._send(413, {"error": "Body too large or missing Content-Length"})
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "Invalid JSON"})
            return None

    def do_POST(self):
        route, ctx = self._guard()
        if route is None:
            return
        if route == "/mcp":
            msg = self._read_json()
            if msg is None:
                return
            if isinstance(msg, list):  # JSON-RPC batch
                out = [r for r in (handle_rpc(m, ctx) for m in msg) if r is not None]
                return self._send(200, out) if out else self._send(202)
            resp = handle_rpc(msg, ctx)
            return self._send(202) if resp is None else self._send(200, resp)
        if route == "/query":
            body = self._read_json()
            if body is None:
                return
            res = execute_logged(body.get("db"), body.get("sql"), ctx, "http")
            payload = json.loads(res["content"][0]["text"])
            return self._send(400 if res["isError"] else 200, payload)
        self._send(404, {"error": "Not found"})

    def do_GET(self):
        route, ctx = self._guard()
        if route is None:
            return
        if route == "/health":
            return self._send(200, {"status": "ok", "allowed_dbs": list(ALLOWED_DBS), "read_only": True})
        self._send(405, {"error": "Use POST"})  # no server-initiated SSE stream offered

    def do_PUT(self):
        self._deny_verb()

    def do_PATCH(self):
        self._deny_verb()

    def do_DELETE(self):
        self._deny_verb()

    def _deny_verb(self):
        route, ctx = self._guard()
        if route is None:
            return
        self._send(405, {"error": "Method not allowed"})


def main():
    token = os.environ.get("BRIDGE_TOKEN", "")
    if len(token) < 24:
        print("ERROR: set BRIDGE_TOKEN (>= 24 chars), e.g.  export BRIDGE_TOKEN=$(openssl rand -hex 24)", file=sys.stderr)
        sys.exit(1)
    missing = [k for k in ("METABASE_URL", "METABASE_USER", "METABASE_PASSWORD") if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing in environment/.env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    os.environ.setdefault("METABASE_DB_ID", "69")
    port = int(os.environ.get("BRIDGE_PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # loopback only; the tunnel connects to this
    srv.token = token
    log("server_start", host="127.0.0.1", port=port, allowed_dbs=list(ALLOWED_DBS), max_rows=CFG["max_rows"],
        timeout_s=CFG["timeout_s"], url_token_enabled=CFG["allow_url_token"])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("server_stop")


if __name__ == "__main__":
    main()
