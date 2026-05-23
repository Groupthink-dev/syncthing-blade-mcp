# Changelog

All notable changes to `syncthing-blade-mcp` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.8.0] - 2026-05-24

### Changed

- **DD-338 Phase E.python — depend on `stallari-mcp-helpers>=0.1.0,<1.0.0`.**
  Local `meta_envelope` + `append_meta` helpers in `formatters.py` deleted;
  canonical implementations are now re-exported from the lib for backward
  call-site compatibility.
- **`append_meta` signature is now `(body, meta_line)`** (lib semantics) where
  it previously accepted kwargs and built the envelope internally. The 11
  call-sites in `tools/folders.py`, `tools/instances.py`, `tools/system.py`,
  and `tools/devices.py` were refactored to the two-step pattern
  `append_meta(payload, meta_envelope(...))`.

### Wire-shape change (test fixtures updated)

- `_meta.filtered_by` continues to be sorted alphabetically inside the helper
  (unchanged — was already the behaviour of the local helper).
- `_meta` field order now follows the canonical lib convention
  (`matched_total`, `returned`, `latency_ms`, `filtered_by`, `redactions`,
  `next_cursor`, `error_notes?`, `domain_hints?`). The prior local helper
  emitted `latency_ms` last.
- `_meta.next_cursor` is now always present (defaults to `null`); the prior
  local helper omitted it entirely. The semantic OQ-4 invariant ("no cursor
  surfaced to callers in v1") is unchanged.
- `_meta.redactions` continues to be emitted unconditionally as `[]` when
  empty (unchanged).
- `_meta.error_notes` and `_meta.domain_hints` remain conditionally included
  only when non-empty (unchanged).

### Notes

- Pure substrate swap — no behavioural change to any tool. Pack-spec catalog
  declarations unchanged.

