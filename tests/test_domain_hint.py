"""DD-338 A.2.dom.c — domain_hint pattern engine smoke-tests.

DD-338 Phase E.python — the pattern engine moved from the local
``syncthing_mcp.domain_hint`` module to the canonical
``stallari_mcp_helpers`` package. These tests now exercise the lib's
public surface and serve as a lightweight blade-side smoke-test
confirming the lib resolves the record shapes this blade emits
(folders + devices) correctly. The lib's own test suite is the
authoritative coverage layer.
"""

from __future__ import annotations

from stallari_mcp_helpers import (
    Pattern,
    compute_domain_hint,
    load_patterns_from_yaml,
)


# ---------------------------------------------------------------------------
# compute_domain_hint
# ---------------------------------------------------------------------------


def test_empty_patterns_returns_none() -> None:
    """No patterns ⇒ no domain hint regardless of record shape."""
    record = {"id": "test", "label": "Test", "path": "/Family/photos"}
    assert compute_domain_hint(record, []) is None


def test_single_pattern_match_folder() -> None:
    """A folder record matches a contains pattern on path."""
    record = {
        "id": "photos-2026",
        "label": "Family Photos",
        "path": "/Volumes/Storage/Family/Photos",
        "type": "sendreceive",
    }
    patterns = [Pattern(field="path", op="contains", value="/Family/", domain="family")]
    assert compute_domain_hint(record, patterns) == "family"


def test_first_match_wins() -> None:
    """When two patterns match the same record, the first one in the list wins."""
    record = {
        "id": "work-docs",
        "label": "Work Docs",
        "path": "/work/Family/shared",
        "type": "sendreceive",
    }
    patterns = [
        Pattern(field="path", op="contains", value="/work/", domain="work"),
        Pattern(field="path", op="contains", value="/Family/", domain="family"),
    ]
    assert compute_domain_hint(record, patterns) == "work"


def test_glob_wildcard_on_label() -> None:
    """fnmatch glob op handles wildcard label matches."""
    record = {"id": "f1", "label": "Work Notes", "path": "/x"}
    patterns = [Pattern(field="label", op="glob", value="Work*", domain="work")]
    assert compute_domain_hint(record, patterns) == "work"


def test_unknown_field_returns_none() -> None:
    """Unknown field path ⇒ no match, no crash."""
    record = {"id": "f1", "label": "L", "path": "/x"}
    patterns = [Pattern(field="nonsense", op="equals", value="x", domain="d")]
    assert compute_domain_hint(record, patterns) is None


def test_device_record_addresses_list_match() -> None:
    """List-valued projector return (addresses) matches element-wise."""
    record = {
        "deviceID": "ABCDEFG-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA",
        "name": "ops-host",
        "addresses": ["dynamic", "tcp://10.0.0.5:22000"],
    }
    patterns = [Pattern(field="addresses", op="contains", value="10.0.0.5", domain="ops")]
    assert compute_domain_hint(record, patterns) == "ops"


def test_device_record_equals_deviceid() -> None:
    """Exact deviceID match emits the configured domain."""
    record = {"deviceID": "ABCDEFG-XYZ", "name": "h"}
    patterns = [Pattern(field="deviceID", op="equals", value="ABCDEFG-XYZ", domain="ops")]
    assert compute_domain_hint(record, patterns) == "ops"


# ---------------------------------------------------------------------------
# load_patterns_from_yaml
# ---------------------------------------------------------------------------


def test_load_patterns_empty_string() -> None:
    assert load_patterns_from_yaml("") == []
    assert load_patterns_from_yaml("   \n  ") == []


def test_load_patterns_well_formed() -> None:
    yaml_str = """
patterns:
  - field: path
    op: contains
    value: /Family/
    domain: family
  - field: label
    op: glob
    value: Work*
    domain: work
"""
    result = load_patterns_from_yaml(yaml_str)
    assert len(result) == 2
    assert result[0] == Pattern(field="path", op="contains", value="/Family/", domain="family")
    assert result[1] == Pattern(field="label", op="glob", value="Work*", domain="work")


def test_load_patterns_missing_key_skipped() -> None:
    """Per-pattern parse failures are silently skipped; good entries kept."""
    yaml_str = """
patterns:
  - field: path
    op: contains
    value: /ok/
    domain: ok
  - field: path
    op: contains
    domain: missing_value
"""
    result = load_patterns_from_yaml(yaml_str)
    assert len(result) == 1
    assert result[0].domain == "ok"


def test_load_patterns_malformed_yaml() -> None:
    """YAML parse error ⇒ empty list (Convention #22 graceful degradation)."""
    yaml_str = "patterns: [unterminated"
    assert load_patterns_from_yaml(yaml_str) == []


def test_load_patterns_non_mapping_root() -> None:
    assert load_patterns_from_yaml("- just\n- a\n- list") == []


def test_load_patterns_missing_patterns_key() -> None:
    assert load_patterns_from_yaml("other_key: value") == []
