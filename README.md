# email.notetoself

A tiny MCP server that emails a note to yourself.

- **Server name:** `email.notetoself`
- **Tool:** `send_note(message: str) -> str`
- **Subject:** `NTS:` + first 20 characters of the note
- **Body:** the full message, exactly as received
- **Auth:** every request must carry `X-Client-ID` and `Authorization: Bearer <token>` matching an entry in `CLIENTS_JSON`

## 1. Install

```bash
cd email-notetoself
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2. Create a Gmail App Password

The server uses Gmail SMTP with an App Password (not your normal Gmail password).

1. Enable **2-Step Verification** on the Google account that will send the email
   (https://myaccount.google.com/security).
2. Open https://myaccount.google.com/apppasswords and create an App Password.
   - App name: anything, e.g. `email-notetoself`
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
| `CLIENTS_JSON`  | JSON map of `client_id` -> `token` (see below)     |

Generate a token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Example `CLIENTS_JSON` for a single trusted client:

```
CLIENTS_JSON={"scott-desktop":"PASTE_TOKEN_HERE"}
```

Multiple clients (each gets its own token):

```
CLIENTS_JSON={"scott-desktop":"token-aaa","scott-phone":"token-bbb"}
```

## 4. Run

```bash
python server.py
```

You should see:

```
email.notetoself ready on 0.0.0.0:3001 (clients=1)
```

Smoke test from another shell:

```bash
curl http://127.0.0.1:3001/health
# {"status":"ok","server":"email.notetoself"}

curl -X POST http://127.0.0.1:3001/mcp \
     -H "X-Client-ID: scott-desktop" \
     -H "Authorization: Bearer PASTE_TOKEN_HERE" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

You should get a response that lists `send_note`. Then call it:

```bash
curl -X POST http://127.0.0.1:3001/mcp \
     -H "X-Client-ID: scott-desktop" \
     -H "Authorization: Bearer PASTE_TOKEN_HERE" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"send_note","arguments":{"message":"remember to buy milk"}}}'
```

The body `"remember to buy milk"` will arrive at `beernutz@gmail.com` with subject `NTS:remember to buy milk`.

## 5. Wire up an MCP client

### Claude Desktop

`~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "email.notetoself": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:3001/mcp",
      "headers": {
        "X-Client-ID": "scott-desktop",
        "Authorization": "Bearer PASTE_TOKEN_HERE"
      }
    }
  }
}
```

If Claude Desktop runs on a different machine on the LAN, replace `127.0.0.1` with the server's LAN IP. Restart Claude Desktop. The `send_note` tool will show up in the tools list.

### Other clients

Any MCP client that supports streamable HTTP works. Point it at
`http://127.0.0.1:3001/mcp` with the two headers above.

## File layout

```
email-notetoself/
|-- server.py            # MCP server entry + Starlette wiring
|-- auth.py              # ASGI middleware: X-Client-ID + Bearer token
|-- mailer.py            # SMTP send + subject/body rules
|-- config.py            # .env loading + validation
|-- requirements.txt
|-- .env.example         # copy to .env and edit
|-- tests/
|   `-- test_mailer_logic.py
|-- deploy/              # systemd unit + env file template
|   |-- email-notetoself.service
|   `-- email-notetoself.env.example
`-- README.md
```

## 6. Run as a systemd service (Linux)

The repo ships a unit file in `deploy/email-notetoself.service` that runs the
server under a dedicated unprivileged user, restarts on failure, and reads
its config from `/etc/email-notetoself/email-notetoself.env`.

```bash
# 1. Pick an install root and clone/copy the repo there.
sudo install -d -o email-notetoself -g email-notetoself -m 0750 /opt/email-notetoself
sudo cp -r . /opt/email-notetoself/
sudo -u email-notetoself python3 -m venv /opt/email-notetoself/.venv
sudo -u email-notetoself /opt/email-notetoself/.venv/bin/pip install -r /opt/email-notetoself/requirements.txt

# 2. Install the env file (mode 0600, owned by the service user).
sudo install -d -o email-notetoself -g email-notetoself -m 0750 /etc/email-notetoself
sudo cp deploy/email-notetoself.env.example /etc/email-notetoself/email-notetoself.env
sudo chmod 0600 /etc/email-notetoself/email-notetoself.env
sudo -u email-notetoself $EDITOR /etc/email-notetoself/email-notetoself.env

# 3. Install + enable the unit.
sudo cp deploy/email-notetoself.service /etc/systemd/system/email-notetoself.service
sudo systemctl daemon-reload
sudo systemctl enable --now email-notetoself.service
sudo systemctl status email-notetoself.service
```

The unit binds to `0.0.0.0:3001` (configurable via the env file) and logs to
the journal (`journalctl -u email-notetoself.service -f`).

## Security notes

- **The server binds to `0.0.0.0` by default, which exposes it to anything
  that can reach the host on `PORT`.** Put the box behind a firewall (drop
  inbound traffic to `3001` from untrusted networks), a reverse proxy with
  TLS, or set `HOST=127.0.0.1` in the env file if you only need local
  clients. `Authorization` headers carry the bearer token in cleartext
  without TLS.
- Tokens are compared with `secrets.compare_digest` (constant-time).
- The server never logs message bodies, only `subject=...` + `body_chars=N`.
- `CLIENTS_JSON` should be treated as a secret. Anyone with a valid
  `client_id`/`token` pair can email as you. Don't commit `.env` or the
  systemd env file.
- SMTP errors (wrong password, blocked sign-in, etc.) are returned to the
  calling LLM as plain text. Don't expose this server on a public network
  without thinking about that.
