"""Tests for Pydantic input model validation."""

import pytest
from pydantic import ValidationError

from syncthing_mcp.models import (
    BrowseFolderInput,
    DeviceInput,
    EmptyInput,
    FileInfoInput,
    FolderInput,
    FolderNeedInput,
    PauseFolderInput,
    SetIgnoresInput,
    _resolve_scope_folders,
)


class TestEmptyInput:
    def test_no_args(self):
        m = EmptyInput()
        assert m.instance is None

    def test_with_instance(self):
        m = EmptyInput(instance="mynas")
        assert m.instance == "mynas"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            EmptyInput(instance="a", extra="bad")


class TestFolderInput:
    def test_valid(self):
        m = FolderInput(folder_id="abc-123")
        assert m.folder_id == "abc-123"

    def test_empty_folder_id(self):
        with pytest.raises(ValidationError):
            FolderInput(folder_id="")

    def test_whitespace_stripped(self):
        m = FolderInput(folder_id="  abc  ")
        assert m.folder_id == "abc"


class TestDeviceInput:
    def test_valid(self):
        m = DeviceInput(device_id="ABCDEF-123456")
        assert m.device_id == "ABCDEF-123456"

    def test_empty_device_id(self):
        with pytest.raises(ValidationError):
            DeviceInput(device_id="")


class TestPauseFolderInput:
    def test_valid(self):
        m = PauseFolderInput(folder_id="f1")
        assert m.folder_id == "f1"


class TestSetIgnoresInput:
    def test_valid(self):
        m = SetIgnoresInput(folder_id="f1", patterns=["*.tmp", ".DS_Store"])
        assert len(m.patterns) == 2


class TestBrowseFolderInput:
    def test_defaults(self):
        m = BrowseFolderInput(folder_id="f1")
        assert m.prefix is None
        assert m.levels is None

    def test_with_prefix(self):
        m = BrowseFolderInput(folder_id="f1", prefix="docs/reports", levels=2)
        assert m.prefix == "docs/reports"
        assert m.levels == 2

    def test_negative_levels(self):
        with pytest.raises(ValidationError):
            BrowseFolderInput(folder_id="f1", levels=-1)


class TestFileInfoInput:
    def test_valid(self):
        m = FileInfoInput(folder_id="f1", file_path="docs/readme.md")
        assert m.file_path == "docs/readme.md"

    def test_empty_file_path(self):
        with pytest.raises(ValidationError):
            FileInfoInput(folder_id="f1", file_path="")


class TestFolderNeedInput:
    def test_defaults(self):
        m = FolderNeedInput(folder_id="f1")
        assert m.page == 1
        assert m.per_page == 50

    def test_custom_pagination(self):
        m = FolderNeedInput(folder_id="f1", page=3, per_page=100)
        assert m.page == 3
        assert m.per_page == 100

    def test_page_must_be_positive(self):
        with pytest.raises(ValidationError):
            FolderNeedInput(folder_id="f1", page=0)

    def test_per_page_max(self):
        with pytest.raises(ValidationError):
            FolderNeedInput(folder_id="f1", per_page=501)


# ---------------------------------------------------------------------------
# DD-338 Phase A.1 — Track 1 — _resolve_scope_folders helper
# ---------------------------------------------------------------------------


class TestResolveScopeFolders:
    def test_none_scope_returns_none(self):
        s, r = _resolve_scope_folders(None, None)
        assert s is None
        assert r == []

    def test_public_raises(self):
        with pytest.raises(ValueError, match="public"):
            _resolve_scope_folders("public", None)

    def test_unknown_scope_treated_as_unconfigured(self):
        s, r = _resolve_scope_folders("bogus", None)
        assert s is None
        assert r == ["scope=bogus_unconfigured"]

    def test_configured_env_var(self, monkeypatch):
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld1, fld2,fld3")
        s, r = _resolve_scope_folders("work", None)
        assert s == {"fld1", "fld2", "fld3"}
        assert r == []

    def test_empty_env_var_matches_nothing(self, monkeypatch):
        monkeypatch.setenv("SYNCTHING_PERSONAL_FOLDERS", "")
        s, r = _resolve_scope_folders("personal", None)
        # Empty env still counts as configured but yields empty set
        assert s == set()
        assert r == []

    def test_unconfigured_in_vocab_redacts(self, monkeypatch):
        monkeypatch.delenv("SYNCTHING_FAMILY_FOLDERS", raising=False)
        s, r = _resolve_scope_folders("family", None)
        assert s is None
        assert r == ["scope=family_unconfigured"]

    def test_per_instance_env_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld-default")
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS_VIKING", "fld-viking1,fld-viking2")
        s, _ = _resolve_scope_folders("work", "viking")
        assert s == {"fld-viking1", "fld-viking2"}

    def test_per_instance_falls_back_to_base(self, monkeypatch):
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld-default")
        monkeypatch.delenv("SYNCTHING_WORK_FOLDERS_VOYAGER", raising=False)
        s, _ = _resolve_scope_folders("work", "voyager")
        assert s == {"fld-default"}
