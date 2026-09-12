"""Tests for Ansible filter plugins."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add ansible filter_plugins to path
filter_plugins_path = Path(__file__).parent.parent.parent / "ansible" / "filter_plugins"
sys.path.insert(0, str(filter_plugins_path))

from pmx_filters import pmx_parse_cephfs  # noqa: E402


class TestPmxParseCephfs:
    """Test pmx_parse_cephfs filter function."""

    def test_parse_simple_subpath(self):
        """Parses 'subpath:/dest' into structured dict."""
        result = pmx_parse_cephfs("supernote:/mnt/sn")
        assert result == {"subpath": "/supernote", "dest": "/mnt/sn"}

    def test_parse_subpath_with_slash(self):
        """Subpath already starting with / is not doubled."""
        result = pmx_parse_cephfs("/supernote:/mnt/sn")
        assert result == {"subpath": "/supernote", "dest": "/mnt/sn"}

    def test_parse_nested_dest_path(self):
        """Destination can be a nested path."""
        result = pmx_parse_cephfs("data:/media/shared/data")
        assert result == {"subpath": "/data", "dest": "/media/shared/data"}

    def test_parse_empty_subpath(self):
        """Empty subpath (root ceph mount) becomes '/'."""
        result = pmx_parse_cephfs(":/mnt/root")
        assert result == {"subpath": "/", "dest": "/mnt/root"}

    def test_reject_missing_colon(self):
        """Raises ValueError if ':' is missing."""
        with pytest.raises(ValueError, match="must be '<subpath>:<guest-path>'"):
            pmx_parse_cephfs("no_colon")

    def test_reject_malformed_spec(self):
        """Raises ValueError with helpful message on malformed input."""
        with pytest.raises(ValueError, match="must be '<subpath>:<guest-path>'"):
            pmx_parse_cephfs("invalid")

    def test_multiple_colons_splits_on_first(self):
        """If multiple colons, split on the first one only."""
        result = pmx_parse_cephfs("sub:path:/mnt/dir:with:colons")
        assert result == {"subpath": "/sub", "dest": "path:/mnt/dir:with:colons"}

    def test_reject_trailing_colon(self):
        """Raises ValueError if destination is empty (trailing colon)."""
        with pytest.raises(ValueError, match="destination cannot be empty"):
            pmx_parse_cephfs("foo:")


from pmx_filters import pmx_cephx_caps


class TestPmxCephxCaps:
    """pmx_cephx_caps must produce exactly the strings `ceph fs authorize` writes."""

    def test_single_path(self):
        assert pmx_cephx_caps([{"subpath": "/supernote", "dest": "/mnt/sn"}]) == {
            "mds": "allow rw fsname=cephfs path=/supernote",
            "mon": "allow r fsname=cephfs",
            "osd": "allow rw tag cephfs data=cephfs",
        }

    def test_two_paths_join_with_comma(self):
        specs = [
            {"subpath": "/nextclouddata", "dest": "/mnt/ncd"},
            {"subpath": "/ncdata", "dest": "/mnt/nc"},
        ]
        assert pmx_cephx_caps(specs)["mds"] == (
            "allow rw fsname=cephfs path=/nextclouddata, allow rw fsname=cephfs path=/ncdata"
        )

    def test_root_path_has_no_path_clause(self):
        assert pmx_cephx_caps([{"subpath": "/", "dest": "/mnt/cephfs"}])["mds"] == (
            "allow rw fsname=cephfs"
        )

    def test_custom_fs_name(self):
        caps = pmx_cephx_caps([{"subpath": "/x", "dest": "/mnt/x"}], fs_name="tank")
        assert caps == {
            "mds": "allow rw fsname=tank path=/x",
            "mon": "allow r fsname=tank",
            "osd": "allow rw tag cephfs data=tank",
        }
