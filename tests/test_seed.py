"""Tests for pmx.seed module."""

from __future__ import annotations

from unittest.mock import patch

from pmx.config import Config
from pmx.seed import run


class TestSeedRun:
    """Test suite for seed.run function."""

    @patch("pmx.seed.run_playbook")
    @patch("pmx.seed.load")
    def test_run_calls_run_playbook_with_config_vars(self, mock_load, mock_run_playbook):
        """run() calls run_playbook with extra_vars derived from config."""
        # Arrange: Real Config with test values
        test_config = Config(
            proxmox_ssh_host="root@test",
            proxmox_api_host="test",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="test.local",
            ad_realm="TEST.LOCAL",
            ad_join_user="testuser",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.1.1"],
            state_log_path="state/guests.jsonl",
        )
        mock_load.return_value = test_config

        mock_run_playbook.return_value = 0

        # Act
        result = run()

        # Assert: run_playbook called with seed.yml and correct extra_vars
        expected_extra_vars = {
            "target_node": "pve01",
            "default_storage": "bwrx",
            "default_lxc_storage": "cephfs",
            "default_bridge": "vmbr0",
        }
        mock_run_playbook.assert_called_once_with("seed.yml", expected_extra_vars)
        assert result == 0

    @patch("pmx.seed.run_playbook")
    @patch("pmx.seed.load")
    def test_run_returns_playbook_exit_code(self, mock_load, mock_run_playbook):
        """run() returns the exit code from run_playbook."""
        test_config = Config(
            proxmox_ssh_host="root@test",
            proxmox_api_host="test",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="test.local",
            ad_realm="TEST.LOCAL",
            ad_join_user="testuser",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.1.1"],
            state_log_path="state/guests.jsonl",
        )
        mock_load.return_value = test_config

        mock_run_playbook.return_value = 42

        result = run()

        assert result == 42

    @patch("pmx.seed.run_playbook")
    @patch("pmx.seed.load")
    def test_run_prints_status_message(self, mock_load, mock_run_playbook, capsys):
        """run() prints a status message to stderr."""
        test_config = Config(
            proxmox_ssh_host="root@test",
            proxmox_api_host="test",
            default_node="pve01",
            default_storage="bwrx",
            default_lxc_storage="cephfs",
            default_bridge="vmbr0",
            ad_domain="test.local",
            ad_realm="TEST.LOCAL",
            ad_join_user="testuser",
            ceph_conf_path="/etc/ceph/ceph.conf",
            ceph_secret_path="/etc/ceph/cephfs.secret",
            ceph_mons=["192.168.1.1"],
            state_log_path="state/guests.jsonl",
        )
        mock_load.return_value = test_config

        mock_run_playbook.return_value = 0

        run()

        captured = capsys.readouterr()
        assert "Seeding templates on node pve01" in captured.err
