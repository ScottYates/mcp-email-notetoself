# notetoself

A tiny MCP server that emails a note to yourself.

- **Server name:** `notetoself`
- **Tool:** `send_note(message: str) -> str`
- **Subject:** `NTS:` + first 20 characters of the note
- **Body:** the full message, exactly as received
- **Transport:** legacy SSE. Clients `GET /mcp` to open the event stream and POST to `/mcp/posts/` for messages back.
- **Auth:** every request must carry `Authorization: Bearer <token>` matching an entry in `TOKENS_JSON`

## 1. Install

```bash
cd notetoself
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2. Create a Gmail App Password

The server uses Gmail SMTP with an App Password (not your normal Gmail password).

1. Enable **2-Step Verification** on the Google account that will send the email
   (https://myaccount.google.com/security).
2. Open https://myaccount.google.com/apppasswords and create an App Password.
   - App name: anything, e.g. `notetoself`
   - Google shows you a 16-character password; copy it.
3. That's your `SMTP_PASS`.

## 3. Configure

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
$EDITOR .env
```

Set at minimum:

| Variable        | Value                                              |
| --------------- | -------------------------------------------------- |
| `SMTP_USER`     | `beernutz@gmail.com` (the sending account)         |
| `SMTP_PASS`     | The 16-char App Password from step 2               |
| `TO_EMAIL`      | `beernutz@gmail.com` (where notes go; defaults to `SMTP_USER`) |
| `TOKENS_JSON`   | JSON array of allowed bearer tokens (see below)    |
| `ALLOWED_HOSTS` | Comma-separated list of allowed `Host` headers (see below) |

Generate a token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Example `TOKENS_JSON` with a single trusted token:

```
TOKENS_JSON=["PASTE_TOKEN_HERE"]
```

Multiple clients (each gets its own token):

```
TOKENS_JSON=["token-aaa","token-bbb"]
```

`ALLOWED_HOSTS` lists the `Host` header values the MCP transport security
layer will accept. Defaults to loopback only. **If you reach the server via
a reverse proxy on a public domain (e.g. `https://yatesframe.com/mcp`),
that domain must appear here** or every request gets HTTP 421
("Invalid Host header"). The corresponding `Origin` header is whitelisted
automatically: loopback hosts pair with `http://`, everything else with
`https://`.

```
ALLOWED_HOSTS=127.0.0.1,localhost,[::1],yatesframe.com
```

## 4. Run

```bash
python server.py
```

You should see:

```
notetoself ready on 0.0.0.0:3001 (tokens=1, transport=sse)
```

Smoke test from another shell:

```bash
curl http://localhost:3001/health
# {"status":"ok","server":"notetoself"}

# Open the SSE stream. The first event the server sends is the message
# post URL it expects clients to use. Use -N so curl streams the output
# instead of buffering until disconnect.
curl -N http://localhost:3001/mcp \
     -H "Authorization: Bearer PASTE_TOKEN_HERE" \
     -H "Accept: text/event-stream"
```

The first line you receive is the `endpoint` event telling you where to
POST messages (it'll be `/mcp/posts/?session_id=<hex>`). You won't get a
plain `tools/list` response from `curl` -- real MCP clients (Claude
Desktop, Cursor, etc.) handle the SSE protocol end-to-end.

The body `"remember to buy milk"` will arrive at `beernutz@gmail.com` with subject `NTS:remember to buy milk`.

## 5. Wire up an MCP client

### Claude Desktop

`~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "notetoself": {
      "type": "sse",
      "url": "http://localhost:3001/mcp",
      "headers": {
        "Authorization": "Bearer PASTE_TOKEN_HERE"
      }
    }
  }
}
```

Note the `type: "sse"`: this server uses the legacy SSE transport, not
streamable HTTP. The URL is `/mcp` (the SSE stream endpoint); the message
post URL is discovered automatically from the server's `endpoint` SSE
event.

If Claude Desktop runs on a different machine on the LAN, replace `localhost` with the server's LAN IP. Restart Claude Desktop. The `send_note` tool will show up in the tools list.

### Other clients

Any MCP client that supports streamable HTTP works. Point it at
`http://localhost:3001/mcp` with the single `Authorization` header above.

## File layout

```
notetoself/
|-- server.py            # MCP server entry + Starlette wiring
|-- auth.py              # ASGI middleware: bearer-token allowlist
|-- mailer.py            # SMTP send + subject/body rules
|-- config.py            # .env loading + validation
|-- requirements.txt
|-- .env.example         # copy to .env and edit
|-- tests/
|   `-- test_mailer_logic.py
|-- deploy/              # systemd unit + env file template + nginx config
|   |-- notetoself.service
|   |-- notetoself.env.example
|   `-- nginx.conf.example
`-- README.md
```

## 6. Run as a systemd service (Linux)

The repo ships a unit file in `deploy/notetoself.service` that runs the
server under a dedicated unprivileged user, restarts on failure, and reads
its config from `/opt/notetoself/.env` (in the app folder).

```bash
# 1. Pick an install root and clone/copy the repo there.
sudo install -d -o notetoself -g notetoself -m 0750 /opt/notetoself
sudo cp -r . /opt/notetoself/
sudo -u notetoself python3 -m venv /opt/notetoself/.venv
sudo -u notetoself /opt/notetoself/.venv/bin/pip install -r /opt/notetoself/requirements.txt

# 2. Install the env file in the app folder (mode 0600, owned by the service user).
sudo install -o notetoself -g notetoself -m 0644 \
     deploy/notetoself.env.example /opt/notetoself/.env
sudo chmod 0600 /opt/notetoself/.env
sudo -u notetoself $EDITOR /opt/notetoself/.env

# 3. Install + enable the unit.
sudo cp deploy/notetoself.service /etc/systemd/system/notetoself.service
sudo systemctl daemon-reload
sudo systemctl enable --now notetoself.service
sudo systemctl status notetoself.service
```

The unit binds to `0.0.0.0:3001` (configurable via the env file) and logs to
the journal (`journalctl -u notetoself.service -f`).

## 7. Reverse proxy with nginx

If you're exposing the server on a public domain (e.g.
`https://yatesframe.com/mcp`), put nginx in front of uvicorn. SSE is
notoriously easy to break with default nginx settings, so use the
config in `deploy/nginx.conf.example` rather than rolling your own.
The two non-obvious requirements:

- **`proxy_buffering off;`** — without it, nginx buffers the SSE stream
  and your MCP client times out before the first event arrives.
- **No URI in `proxy_pass`.** Use `proxy_pass http://127.0.0.1:3001;` and
  `location /mcp`, **not** `proxy_pass http://127.0.0.1:3001/mcp;`. The
  URI form rewrites `/mcp/posts/` to `/mcpposts/` at the backend and
  breaks the message path.

Also make sure `ALLOWED_HOSTS` in the env file includes the public
domain — otherwise transport security rejects every request with 421.

```nginx
# /etc/nginx/sites-enabled/notetoself (or included from your server block)
location /mcp {
    proxy_pass http://127.0.0.1:3001;
    proxy_redirect off;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
    chunked_transfer_encoding off;
}
```

## Security notes

- **The server binds to `0.0.0.0` by default, which exposes it to anything
  that can reach the host on `PORT`.** Put the box behind a firewall (drop
  inbound traffic to `3001` from untrusted networks), a reverse proxy with
  TLS, or restrict `HOST` to a loopback address in the env file if you only
  need local clients. `Authorization` headers carry the bearer token in
  cleartext without TLS.
- **MCP DNS-rebinding protection is on by default.** The `ALLOWED_HOSTS`
  list governs which `Host` header values are accepted; `Origin` headers
  are matched against the same list with a sensible scheme prefix. Add
  every public domain the server will be reached under, or clients will
  see HTTP 421 "Invalid Host header".
- Tokens are compared with `secrets.compare_digest` (constant-time).
- The server never logs message bodies, only `subject=...` + `body_chars=N`.
- `TOKENS_JSON` should be treated as a secret. Anyone with one of the
  listed tokens can email as you. Don't commit `.env` or the systemd env
  file.
- SMTP errors (wrong password, blocked sign-in, etc.) are returned to the
  calling LLM as plain text. Don't expose this server on a public network
  without thinking about that.
