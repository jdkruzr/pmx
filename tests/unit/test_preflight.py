"""Tests for pmx.preflight — name uniqueness and SSH reachability."""

from __future__ import annotations

import pytest
import click
from unittest.mock import MagicMock

from pmx.preflight import assert_name_available, _parse_names
from pmx.config import Config


class TestParseNames:
    """Tests for _parse_names — extracting guest names from qm list; pct list output."""

    def test_parse_names_empty_output(self) -> None:
        """Given empty output, _parse_names returns empty set."""
        result = _parse_names("")
        assert result == set()

    def test_parse_names_single_vm(self) -> None:
        """Given qm list with one VM, _parse_names returns set containing VM name."""
        output = """VMID NAME                 STATUS     MEM(M)    MAXMEM(M)    UPTIME
    100 neptune              running       512      2048       10d
"""
        result = _parse_names(output)
        assert "neptune" in result

    def test_parse_names_multiple_vms(self) -> None:
        """Given multiple VMs, _parse_names returns all names."""
        output = """VMID NAME                 STATUS     MEM(M)    MAXMEM(M)    UPTIME
    100 neptune              running       512      2048       10d
    101 aurora               stopped       0        2048        0h
"""
        result = _parse_names(output)
        assert "neptune" in result
        assert "aurora" in result

    def test_parse_names_skips_headers(self) -> None:
        """Given output with headers, _parse_names skips them."""
        output = """VMID NAME STATUS
    100 neptune running
"""
        result = _parse_names(output)
        # Should have neptune but not VMID or NAME
        assert "neptune" in result
        assert "VMID" not in result

    def test_parse_names_handles_separator(self) -> None:
        """Given qm list; echo ---; pct list format, _parse_names handles separator."""
        output = """VMID NAME          STATUS
    100 neptune       running
---
VMID STATUS LOCK NAME
    200 running       0 jupiter
"""
        result = _parse_names(output)
        assert "neptune" in result
        assert "jupiter" in result
        assert "---" not in result

    def test_parse_names_with_hyphenated_names(self) -> None:
        """Given hyphenated VM names, _parse_names includes them."""
        output = """VMID NAME                 STATUS
    100 test-vm-01           running
    101 my-test-container    running
"""
        result = _parse_names(output)
        assert "test-vm-01" in result
        assert "my-test-container" in result

    def test_parse_names_pct_list_format(self) -> None:
        """Given pct list output with separator, _parse_names extracts container names."""
        output = """---
VMID STATUS LOCK NAME
    200 running       0 ubuntu-container
    201 stopped       0 rocky-lxc
"""
        result = _parse_names(output)
        assert "ubuntu-container" in result
        assert "rocky-lxc" in result


class TestAssertNameAvailable:
    """Tests for assert_name_available — ensuring VM/LXC names don't exist."""

    def test_assert_name_available_when_name_not_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given name not in cluster, assert_name_available returns normally."""
        cfg = Config(
            proxmox_ssh_host="root@192.168.9.12",
            proxmox_api_host="192.168.9.12",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="broken.wrx",
            ad_realm="BROKEN.WRX",
            ad_join_user="jtd",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.9.11"],
            state_log_path="state/guests.jsonl",
        )

        import subprocess
        mock_run = MagicMock()
        mock_run.return_value.stdout = """VMID NAME          STATUS
    100 neptune       running
    101 aurora        stopped
"""
        monkeypatch.setattr(subprocess, "run", mock_run)

        # Should not raise
        assert_name_available(cfg, "newhost")

    def test_assert_name_available_raises_when_name_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given name already in cluster, assert_name_available raises click.Abort."""
        cfg = Config(
            proxmox_ssh_host="root@192.168.9.12",
            proxmox_api_host="192.168.9.12",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="broken.wrx",
            ad_realm="BROKEN.WRX",
            ad_join_user="jtd",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.9.11"],
            state_log_path="state/guests.jsonl",
        )

        import subprocess
        mock_run = MagicMock()
        mock_run.return_value.stdout = """VMID NAME          STATUS
    100 neptune       running
    101 aurora        stopped
"""
        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(click.Abort):
            assert_name_available(cfg, "neptune")

    def test_assert_name_available_handles_ssh_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given SSH fails, assert_name_available raises click.Abort."""
        cfg = Config(
            proxmox_ssh_host="root@192.168.9.12",
            proxmox_api_host="192.168.9.12",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="broken.wrx",
            ad_realm="BROKEN.WRX",
            ad_join_user="jtd",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.9.11"],
            state_log_path="state/guests.jsonl",
        )

        import subprocess
        mock_run = MagicMock()
        mock_run.side_effect = subprocess.CalledProcessError(1, "ssh")
        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(click.Abort):
            assert_name_available(cfg, "newhost")

    def test_assert_name_available_handles_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given SSH times out, assert_name_available raises click.Abort."""
        cfg = Config(
            proxmox_ssh_host="root@192.168.9.12",
            proxmox_api_host="192.168.9.12",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="broken.wrx",
            ad_realm="BROKEN.WRX",
            ad_join_user="jtd",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.9.11"],
            state_log_path="state/guests.jsonl",
        )

        import subprocess
        mock_run = MagicMock()
        mock_run.side_effect = subprocess.TimeoutExpired("ssh", 15)
        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(click.Abort):
            assert_name_available(cfg, "newhost")

    def test_assert_name_available_rejects_invalid_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given invalid name (starting with hyphen, containing spaces, etc), assert_name_available raises click.Abort."""
        cfg = Config(
            proxmox_ssh_host="root@192.168.9.12",
            proxmox_api_host="192.168.9.12",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="broken.wrx",
            ad_realm="BROKEN.WRX",
            ad_join_user="jtd",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.9.11"],
            state_log_path="state/guests.jsonl",
        )

        # Should not make SSH call — fail before that
        import subprocess
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        # Test various invalid patterns
        invalid_names = ["-invalid", "name_underscore", "name with spaces", "name.dot", ""]
        for invalid_name in invalid_names:
            with pytest.raises(click.Abort):
                assert_name_available(cfg, invalid_name)
            # Mock should not have been called for invalid names
        assert mock_run.call_count == 0

    def test_assert_name_available_accepts_valid_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given valid names (alphanumeric + hyphens starting with alphanumeric), assert_name_available doesn't reject early."""
        cfg = Config(
            proxmox_ssh_host="root@192.168.9.12",
            proxmox_api_host="192.168.9.12",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="broken.wrx",
            ad_realm="BROKEN.WRX",
            ad_join_user="jtd",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.9.11"],
            state_log_path="state/guests.jsonl",
        )

        import subprocess
        mock_run = MagicMock()
        mock_run.return_value.stdout = ""
        monkeypatch.setattr(subprocess, "run", mock_run)

        # Valid names should pass validation and attempt SSH call
        valid_names = ["myhost", "test-vm-01", "a", "ABC123", "host1-2-3"]
        for valid_name in valid_names:
            assert_name_available(cfg, valid_name)

    def test_assert_name_available_checks_ssh_invocation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given valid name, assert_name_available invokes SSH with proper arguments."""
        cfg = Config(
            proxmox_ssh_host="root@192.168.9.12",
            proxmox_api_host="192.168.9.12",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="broken.wrx",
            ad_realm="BROKEN.WRX",
            ad_join_user="jtd",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.9.11"],
            state_log_path="state/guests.jsonl",
        )

        import subprocess
        mock_run = MagicMock()
        mock_run.return_value.stdout = ""
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert_name_available(cfg, "testhost")

        # Verify mock was called once
        assert mock_run.call_count == 1
        # Get the command list (first positional arg)
        call_args = mock_run.call_args
        cmd = call_args[0][0]  # First positional argument is the command list
        # Check command contains SSH host
        assert cfg.proxmox_ssh_host in cmd
        # Check command contains BatchMode=yes
        assert "BatchMode=yes" in cmd
