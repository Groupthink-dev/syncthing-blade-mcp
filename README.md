# syncthing-blade-mcp

An MCP (Model Context Protocol) server for [Syncthing](https://syncthing.net/) — the open-source continuous file synchronisation tool.

Built to give AI assistants (Claude, etc.) read and control access to Syncthing's REST API, with a focus on **replication awareness**: understanding which folders are fully replicated across devices so you can confidently reclaim local disk space.

## Key Features

- **Token-efficient output** — compact JSON by default; `concise=false` for full details
- **Multi-instance** — manage multiple Syncthing nodes from a single server
- **Write-gated** — mutating tools require `SYNCTHING_WRITE_ENABLED=true`; destructive operations additionally require `confirm=true`
- **Replication analysis** — safe-to-remove flags and reclaimable space calculation
- **Syncthing v2.x compatible** — tested against v2.0.x REST API
- **HTTP transport** — Streamable HTTP with bearer-token auth, Cloudflare Tunnel support
- **SKILL.md** — LLM skill guide for optimal tool usage

## Tools (39 total)

### Instance Management

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_list_instances` | List all configured instances, probe availability | No |

### System Status & Monitoring

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_system_status` | Device ID, name, uptime, version | No |
| `syncthing_list_folders` | All folders with types and device counts | No |
| `syncthing_list_devices` | All devices with connection status | No |
| `syncthing_connections` | Active connection details | No |
| `syncthing_device_stats` | Per-device statistics (last seen, duration) | No |
| `syncthing_system_errors` | Recent system errors and warnings | No |
| `syncthing_clear_errors` | Clear the system error log | Yes |
| `syncthing_system_log` | Recent log entries | No |
| `syncthing_recent_changes` | Recent file change events (local + remote) | No |
| `syncthing_health_summary` | Single-call health overview with alerts | No |
| `syncthing_check_upgrade` | Check for newer Syncthing version | No |

### Folder Status & Replication

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_folder_status` | Detailed folder metrics (expensive call) | No |
| `syncthing_folder_completion` | Per-device completion % for a folder | No |
| `syncthing_replication_report` | All folders: safe-to-remove + reclaimable space | No |
| `syncthing_folder_errors` | Current sync errors for a folder | No |

### Device Status

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_device_completion` | Aggregated completion for a device | No |

### Folder Operations

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_scan_folder` | Trigger an immediate rescan | Yes |
| `syncthing_pause_folder` | Pause a folder (prevents deletion propagation) | Yes |
| `syncthing_resume_folder` | Resume a paused folder | Yes |

### File-Level Queries

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_browse_folder` | Browse folder contents (directory listing from DB) | No |
| `syncthing_file_info` | Detailed info about a specific file | No |
| `syncthing_folder_need` | Out-of-sync files this folder needs (paginated) | No |
| `syncthing_remote_need` | Files a remote device needs from us (paginated) | No |

### Conflict Resolution

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_override_folder` | Override remote changes (send-only folder) | Yes |
| `syncthing_revert_folder` | Revert local changes (receive-only folder) | Yes |

### Config Mutation: Pending Devices & Folders

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_pending_devices` | List pending device connection requests | No |
| `syncthing_pending_folders` | List pending folder share offers | No |
| `syncthing_accept_device` | Accept a pending device | Yes |
| `syncthing_reject_device` | Dismiss a pending device request | Yes |
| `syncthing_accept_folder` | Accept a pending folder offer | Yes |
| `syncthing_reject_folder` | Dismiss a pending folder offer | Yes |

### Config Mutation: Restart & Ignore Patterns

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_restart_required` | Check if config changes require a restart | No |
| `syncthing_restart` | Restart the Syncthing service | Yes |
| `syncthing_get_ignores` | Get .stignore patterns for a folder | No |
| `syncthing_set_ignores` | Set .stignore patterns for a folder | Yes |
| `syncthing_get_default_ignores` | Get default ignore patterns | No |
| `syncthing_set_default_ignores` | Set default ignore patterns | Yes |

## Write Safety

All mutating tools (the "Yes" rows above) refuse unless the environment variable
`SYNCTHING_WRITE_ENABLED=true` is set. The gate is off by default.

Destructive or disruptive operations additionally require `confirm=true` on the
call itself, with a refusal message explaining what the operation will do:

| Tool | Why confirm is required |
|------|------------------------|
| `syncthing_override_folder` | Pushes local state over remote edits — remote changes discarded cluster-wide |
| `syncthing_revert_folder` | Discards local changes on a receive-only folder |
| `syncthing_restart` | Stops the daemon and interrupts all active sync transfers |
| `syncthing_accept_device` | Admits a pending device into the cluster |
| `syncthing_accept_folder` | Starts syncing a remote folder's contents to local disk |
| `syncthing_set_ignores` | Replaces the folder's entire `.stignore` pattern set |

## Token Efficiency

All read tools default to `concise=true`, producing compact JSON with minimal fields and
short device IDs. Set `concise=false` for full details when debugging.

| Mode | Output style | Use case |
|------|-------------|----------|
| `concise=true` (default) | Compact JSON, short IDs, essential fields | Normal operation |
| `concise=false` | Pretty JSON, full device IDs, all fields | Debugging, raw data |

Large responses are automatically truncated at 25,000 characters with guidance to use
pagination or filters.

See [SKILL.md](SKILL.md) for the complete LLM skill guide.

## Project Structure

```
syncthing-blade-mcp/
├── src/syncthing_mcp/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # Entry point (stdio + HTTP transport)
│   ├── auth.py              # Bearer token middleware
│   ├── client.py            # SyncthingClient (HTTP methods + error handling)
│   ├── formatters.py        # Token-efficient formatting layer
│   ├── models.py            # Pydantic input models (ReadParams / WriteParams)
│   ├── registry.py          # Multi-instance registry from env vars
│   ├── server.py            # FastMCP server + lifespan
│   └── tools/
│       ├── system.py        # System status, health, errors, log, restart, upgrade
│       ├── folders.py       # Folder status, completion, replication, file queries
│       ├── devices.py       # Device listing, completion, connections, stats
│       ├── config.py        # Pending accept/reject, ignore patterns
│       └── instances.py     # Instance listing, folder listing
├── tests/                   # Tests with respx HTTP mocking
├── SKILL.md                 # LLM skill guide
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml       # Traefik reverse proxy (HTTPS/ACME)
└── docker-compose.tunnel.yml # Cloudflare Tunnel (zero-trust)
```

## Multi-Instance Support

Connect to multiple Syncthing nodes simultaneously by setting the `SYNCTHING_INSTANCES` environment variable with a JSON object:

```json
{
  "mini":  {"url": "http://mini.local:8384",  "api_key": "abc123"},
  "tn-sb": {"url": "http://tn-sb.local:8384", "api_key": "def456"},
  "tn-mr2": {"url": "http://tn-mr2.local:8384", "api_key": "ghi789"}
}
```

Every tool accepts an optional `instance` parameter to target a specific node. When only one instance is configured, the parameter can be omitted.

### Claude Desktop config (multi-instance)

```json
{
  "mcpServers": {
    "syncthing": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/syncthing-blade-mcp",
        "run", "python", "-m", "syncthing_mcp"
      ],
      "env": {
        "SYNCTHING_INSTANCES": "{\"mini\":{\"url\":\"http://mini.local:8384\",\"api_key\":\"abc123\"},\"tn-sb\":{\"url\":\"http://tn-sb.local:8384\",\"api_key\":\"def456\"}}"
      }
    }
  }
}
```

## Safe Removal Workflow

1. Run `syncthing_replication_report` — review which folders show `safe: true`
2. Confirm the fully-replicated remote device(s) are the ones you expect
3. `syncthing_pause_folder` — stops Syncthing from propagating local changes
4. Delete the local data outside of Syncthing
5. Optionally remove the folder from this device's config via the Syncthing web UI

> **Important:** Always pause before deleting. In a `sendreceive` folder, deleting files without pausing will propagate the deletion to all connected devices.

The `safe` flag requires: at least one remote device at 100% completion with `remoteState: valid`, the folder in `idle` state, and the folder not paused. This is deliberately conservative.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A running Syncthing instance with API access

### Install

```bash
git clone https://github.com/piersdd/syncthing-blade-mcp.git
cd syncthing-blade-mcp
uv sync
```

### Get your Syncthing API key

Open the Syncthing web UI → Actions → Settings → API Key.

### Configure Claude Desktop (single instance)

```json
{
  "mcpServers": {
    "syncthing": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/syncthing-blade-mcp",
        "run", "python", "-m", "syncthing_mcp"
      ],
      "env": {
        "SYNCTHING_API_KEY": "your-api-key-here",
        "SYNCTHING_URL": "http://localhost:8384"
      }
    }
  }
}
```

## HTTP Transport

### Streamable HTTP (direct)

```bash
MCP_TRANSPORT=streamable-http MCP_AUTH_TOKEN=secret MCP_PORT=8000 syncthing-blade-mcp
```

### Docker + Traefik (HTTPS with ACME/Let's Encrypt)

```bash
cp .env.example .env   # edit API keys and DOMAIN
docker compose up -d
```

This deploys behind Traefik with automatic Let's Encrypt TLS certificates.
The MCP endpoint is available at `https://syncthing-blade-mcp.<DOMAIN>/mcp`.

### Docker + Cloudflare Tunnel (zero-trust, no open ports)

```bash
cp .env.example .env   # edit API keys and CLOUDFLARE_TUNNEL_TOKEN
docker compose -f docker-compose.tunnel.yml up -d
```

Create a tunnel at [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → Networks → Tunnels.
Point the tunnel's public hostname to `http://syncthing-blade-mcp:8000`.
Bearer token auth (`MCP_AUTH_TOKEN`) secures the endpoint; `/health` is unauthenticated for probes.

### Claude Code (remote HTTP)

```json
{
  "mcpServers": {
    "syncthing": {
      "type": "streamable-http",
      "url": "https://syncthing-blade-mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

## Running Tests

```bash
uv sync
uv run pytest -v
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SYNCTHING_API_KEY` | Yes* | — | API key (single-instance mode) |
| `SYNCTHING_URL` | No | `http://localhost:8384` | Base URL (single-instance mode) |
| `SYNCTHING_INSTANCES` | No | — | JSON object for multi-instance mode |
| `MCP_TRANSPORT` | No | `stdio` | Transport: `stdio` or `streamable-http` |
| `MCP_HOST` | No | `0.0.0.0` | HTTP listen host |
| `MCP_PORT` | No | `8000` | HTTP listen port |
| `MCP_AUTH_TOKEN` | No | — | Bearer token for HTTP transport |
| `DOMAIN` | No | — | FQDN for Traefik TLS (docker-compose.yml) |
| `CLOUDFLARE_TUNNEL_TOKEN` | No | — | Tunnel token (docker-compose.tunnel.yml) |

\* Required unless `SYNCTHING_INSTANCES` is set.

## Performance Notes

- `syncthing_folder_status` and `syncthing_replication_report` call Syncthing's `/rest/db/status` endpoint, which is expensive (high CPU/RAM on the Syncthing side). Use judiciously on low-power hardware.
- The replication report makes one `/rest/db/completion` call per remote device per folder.
- `syncthing_health_summary` calls `/rest/db/status` for each folder — equivalent cost.
- Syncthing v2.x uses SQLite (replacing LevelDB). First launch after v1→v2 migration can be lengthy.

## License

MIT
