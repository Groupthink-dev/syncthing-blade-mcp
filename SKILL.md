---
name: syncthing
triggers:
  - syncthing
  - sync
  - replication
  - file sync
  - folders
  - devices
  - disk space
  - safe to remove
  - backup status
  - sync status
---

# Syncthing MCP — Skill Guide

MCP server for managing Syncthing instances. Multi-instance aware. Focus on
replication analysis and safe disk-space reclamation.

## Token Efficiency Rules (MANDATORY)

1. All read tools default to `concise=true` — compact JSON, short device IDs, minimal fields
2. **Start with `syncthing_health_summary`** — single-call overview, avoids multiple queries
3. Use `syncthing_list_folders` before `syncthing_folder_status` to discover folder IDs
4. Use `syncthing_replication_report` for safe-removal analysis (aggregates all folders)
5. Only set `concise=false` when debugging or when the user needs raw details
6. Avoid `syncthing_folder_status` in loops — it is expensive on the Syncthing side

## Quick Start

| Goal | Tool | Notes |
|------|------|-------|
| Overview / triage | `syncthing_health_summary` | Start here. Status, alerts, counts |
| List folders | `syncthing_list_folders` | Folder IDs, types, device counts |
| List devices | `syncthing_list_devices` | Connection status, addresses |
| Safe to delete? | `syncthing_replication_report` | Per-folder safe flag + reclaimable space |
| Folder deep-dive | `syncthing_folder_status` | Expensive — use sparingly |
| Per-device sync | `syncthing_folder_completion` | Completion % per remote device |
| Accept a device | `syncthing_pending_devices` → `syncthing_accept_device` | Two-step |
| Accept a folder | `syncthing_pending_folders` → `syncthing_accept_folder` | Two-step |
| Debug sync issue | `syncthing_folder_errors` + `syncthing_remote_need` | What's stuck and why |
| Check instances | `syncthing_list_instances` | Multi-instance: probe all nodes |

## Workflows

### Daily Health Check
1. `syncthing_health_summary` — review status and alerts
2. If alerts mention pending items → `syncthing_pending_devices` / `syncthing_pending_folders`
3. If alerts mention errors → `syncthing_system_errors` or `syncthing_folder_errors`

### Disk Space Reclamation
1. `syncthing_replication_report` — identify folders with `safe=true`
2. Confirm reclaimable space in `summary.reclaimable`
3. For each folder to remove: `syncthing_pause_folder` → delete local data outside Syncthing
4. Optionally remove the folder from config via Syncthing web UI

### Debugging Incomplete Sync
1. `syncthing_folder_completion` — which device is behind?
2. `syncthing_remote_need` — what files does the remote device need?
3. `syncthing_folder_errors` — any file-level errors blocking sync?
4. `syncthing_connections` — is the device actually connected?

### Accepting New Devices/Folders
1. `syncthing_pending_devices` — review pending requests
2. `syncthing_accept_device` with optional `name` parameter
3. `syncthing_pending_folders` — review offered folders
4. `syncthing_accept_folder` with optional `path` parameter
5. `syncthing_restart_required` — check if restart needed after config changes

### Setting Up Ignore Patterns
1. `syncthing_get_ignores` — review current patterns
2. `syncthing_set_ignores` — replace patterns (common: `*.tmp`, `.DS_Store`, `Thumbs.db`)
3. `syncthing_get_default_ignores` / `syncthing_set_default_ignores` — template for new folders

## Tool Categories

### Read Tools (39 total → concise by default)

**Instance & System:**
`syncthing_list_instances`, `syncthing_system_status`, `syncthing_health_summary`,
`syncthing_system_errors`, `syncthing_system_log`, `syncthing_recent_changes`,
`syncthing_restart_required`, `syncthing_check_upgrade`

**Folders:**
`syncthing_list_folders`, `syncthing_folder_status`, `syncthing_folder_completion`,
`syncthing_replication_report`, `syncthing_folder_errors`, `syncthing_browse_folder`,
`syncthing_file_info`, `syncthing_folder_need`, `syncthing_remote_need`

**Devices:**
`syncthing_list_devices`, `syncthing_device_completion`, `syncthing_connections`,
`syncthing_device_stats`

**Config (read):**
`syncthing_pending_devices`, `syncthing_pending_folders`, `syncthing_get_ignores`,
`syncthing_get_default_ignores`

### Write Tools

`syncthing_clear_errors`, `syncthing_restart`, `syncthing_pause_folder`,
`syncthing_resume_folder`, `syncthing_scan_folder`, `syncthing_override_folder`,
`syncthing_revert_folder`, `syncthing_accept_device`, `syncthing_reject_device`,
`syncthing_accept_folder`, `syncthing_reject_folder`, `syncthing_set_ignores`,
`syncthing_set_default_ignores`

All write tools require the environment variable `SYNCTHING_WRITE_ENABLED=true`
(off by default). Destructive/disruptive tools — `syncthing_override_folder`,
`syncthing_revert_folder`, `syncthing_restart`, `syncthing_accept_device`,
`syncthing_accept_folder`, `syncthing_set_ignores` — additionally require
`confirm=true` in the call; without it they return a refusal explaining what
the operation would do.

## Multi-Instance

When multiple instances are configured, every tool accepts an `instance` parameter.
If omitted with a single instance, it auto-selects. With multiple instances, omitting
`instance` returns an error listing available names.

Use `syncthing_list_instances` to discover instance names and availability.

## Common Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `instance` | string | auto | Target instance name |
| `concise` | bool | `true` | Compact output (read tools only) |
| `folder_id` | string | required | Syncthing folder ID |
| `device_id` | string | required | Full Syncthing device ID |
| `page` / `per_page` | int | 1 / 50 | Pagination for need/remoteneed |

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| 401 Unauthorized | Bad API key | Check `SYNCTHING_API_KEY` or `SYNCTHING_INSTANCES` JSON |
| 403 Forbidden | API key lacks permissions | Regenerate API key in Syncthing web UI |
| Connection refused | Syncthing not running | Start Syncthing or check URL |
| Timeout | Syncthing busy or unreachable | Retry, or check network / firewall |
| "Multiple instances configured" | Missing `instance` param | Specify `instance` name |

## Performance Notes

- `syncthing_folder_status` and `syncthing_replication_report` call `/rest/db/status`
  which is expensive on the Syncthing side (CPU + RAM). Avoid calling in tight loops.
- `syncthing_health_summary` calls `/rest/db/status` per folder — equivalent cost.
- The replication report makes one `/rest/db/completion` call per remote device per
  folder. On large setups this generates significant API traffic.
- Syncthing v2.x uses SQLite (replacing LevelDB). First launch after upgrade may be
  slow due to migration.
