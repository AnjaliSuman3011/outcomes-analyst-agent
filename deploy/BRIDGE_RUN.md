# Read-only bridge: run it on your Mac (first round)
Code: `tools/readonly_bridge.py` (stdlib only, no installs). Built as a **remote MCP server over HTTP** (JSON-RPC at `POST /mcp`, MCP "Streamable HTTP",
one tool `run_readonly_sql`) plus a plain `POST /query` for curl or a custom GPT Action. Binds to `127.0.0.1` only; a tunnel provides the public HTTPS.

## 1. Start it (Terminal tab 1)
```bash
cd /Users/anjaliSuman/outcomes-analyst/outcomes-analyst-agent
export BRIDGE_TOKEN=$(openssl rand -hex 24)      # new token every start; keep it private
echo "$BRIDGE_TOKEN"                             # copy this for the connector
caffeinate -i python3 tools/readonly_bridge.py   # caffeinate keeps the Mac from idle-sleeping while it runs
```
Metabase credentials are read from the git-ignored `.env` (METABASE_URL / METABASE_USER / METABASE_PASSWORD). Nothing secret is in the repo.
Logs: one JSON line per request on screen and in `logs/bridge.log` (git-ignored; contains query text, never the token or password).
Check it (Terminal tab 2): `curl -s -H "Authorization: Bearer $BRIDGE_TOKEN" http://127.0.0.1:8765/health`
Optional limits (env): `BRIDGE_MAX_ROWS` (500), `BRIDGE_TIMEOUT_S` (60), `BRIDGE_RATE_PER_MIN` (60), `BRIDGE_PORT` (8765).

## 2. Tunnel to a public HTTPS URL (Terminal tab 2) -- YOU run this; I did not start any tunnel
```bash
brew install cloudflared                            # one time (not installed yet on this Mac)
cloudflared tunnel --url http://127.0.0.1:8765      # prints https://<random-words>.trycloudflare.com
```
Your MCP endpoint is `https://<random-words>.trycloudflare.com/mcp`. (ngrok also works: `ngrok http 127.0.0.1:8765`, but it needs an ngrok account + authtoken, which is
your click.) **Laptop-bound:** it works only while the Mac is awake, online, and both tabs are running. The quick-tunnel URL **changes every time** cloudflared
restarts, so you must update the connector URL each time. Stop everything with Ctrl+C in both tabs. Anyone with the URL can reach the server, but every request
still needs the token.

## 3. Attach to the Claude Project
Project -> Settings -> Connectors -> Add custom connector -> URL = the `/mcp` address above.
**Open question I could not test from here:** claude.ai's custom-connector form, as I understand it, takes a URL and optional OAuth client id/secret, and may NOT
let you set a static `Authorization: Bearer` header. If it won't send the header, you have two choices:
- **Token-in-URL (stopgap):** restart the bridge with `BRIDGE_ALLOW_URL_TOKEN=1` and use `https://<random-words>.trycloudflare.com/t/<BRIDGE_TOKEN>/mcp` as the connector URL.
  Treat that URL like a password (it is one), never paste it into chat, and rotate by restarting. The bearer header is still accepted too. The logs redact the token.
- **Proper fix:** add OAuth to the bridge (not built). Clients that do send a bearer header (Claude API MCP connector, Claude Code, curl) work today with no change.

## 4. What is guarded (all in code, before Metabase is touched)
Token on every request (constant-time compare; no token = 401, including `/health`) | DB 69 and 434 only (437 refused) | SELECT or WITH...SELECT only, one
statement | a real SQL tokenizer strips strings and comments first (so `'#'` or `'--'` inside a string cannot hide code) | MySQL executable comments `/*! */`
refused | Metabase `{{ }}` / `[[ ]]` templating refused | write keywords, INTO, `@` variables, and SLEEP / BENCHMARK / LOAD_FILE / GET_LOCK and other lock and wait
functions refused | row cap (extra rows dropped, response says `truncated`) | timeout (MySQL `MAX_EXECUTION_TIME` hint on plain SELECTs + a client timeout; a
`WITH` query relies on the client timeout, which stops waiting but may not stop the server query) | max 3 concurrent queries and 60/min | PUT/PATCH/DELETE refused.
Tests: `python3 tests/test_bridge_guard.py` (no network).
**Not a substitute for a read-only DB user:** the Metabase account used is still your current login. Before sharing wider, create the dedicated read-only user.
