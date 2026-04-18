"""Tests for pmx/reconfigure.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pmx.reconfigure import run


def test_reconfigure_missing_state_returns_1() -> None:
    """Test that reconfigure with missing state returns 1."""
    with patch("pmx.reconfigure.load") as mock_load, \
         patch("pmx.reconfigure.find_by_name") as mock_find, \
         patch("pmx.reconfigure.click.echo") as mock_echo:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        mock_load.return_value = cfg

        # State not found
        mock_find.return_value = None

        result = run("nonexistent")

        # Check that error message was printed
        error_calls = [call for call in mock_echo.call_args_list
                      if "No record" in str(call)]
        assert len(error_calls) > 0

        assert result == 1


def test_reconfigure_state_found_builds_correct_extra_vars() -> None:
    """Test that reconfigure with found state builds correct extra_vars."""
    with patch("pmx.reconfigure.load") as mock_load, \
         patch("pmx.reconfigure.find_by_name") as mock_find, \
         patch("pmx.reconfigure.ensure_ad_password") as mock_ad_password, \
         patch("pmx.reconfigure.run_playbook") as mock_playbook:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.default_node = "pve01"
        cfg.ad_domain = "broken.wrx"
        cfg.ad_realm = "BROKEN.WRX"
        cfg.ad_join_user = "jtd"
        cfg.default_storage = "bwrx"
        cfg.default_lxc_storage = "cephfs"
        cfg.default_bridge = "vmbr0"
        cfg.proxmox_api_host = "192.168.9.12"
        mock_load.return_value = cfg

        # State found
        state = MagicMock()
        state.hostname = "testhost"
        state.vmid = 101
        state.kind = "vm"
        state.os = "ubuntu"
        state.ip = "192.168.9.80"
        state.mac = "aa:bb:cc:dd:ee:ff"
        state.domain_joined = True
        state.cephfs_mounts = ["data:/mnt/data"]
        state.rbd_disk = 20
        state.extra_packages = ["git", "curl"]
        state.static_ip = "192.168.9.80/24"
        state.static_gw = "192.168.9.1"
        mock_find.return_value = state

        mock_playbook.return_value = 0

        result = run("testhost")

        # Verify ensure_ad_password was called
        mock_ad_password.assert_called_once()

        # Verify playbook was called with correct extra_vars
        mock_playbook.assert_called_once()
        call_args = mock_playbook.call_args
        assert call_args[0][0] == "reconfigure.yml"
        extra_vars = call_args[0][1]

        # Verify all required keys are present
        assert extra_vars["target_node"] == "pve01"
        assert extra_vars["guest_name"] == "testhost"
        assert extra_vars["guest_vmid"] == 101
        assert extra_vars["guest_kind"] == "vm"
        assert extra_vars["guest_os"] == "ubuntu"
        assert extra_vars["guest_ip"] == "192.168.9.80"
        assert extra_vars["guest_mac"] == "aa:bb:cc:dd:ee:ff"
        assert extra_vars["domain_join"] is True
        assert extra_vars["cephfs_mounts"] == ["data:/mnt/data"]
        assert extra_vars["rbd_disk"] == 20
        assert extra_vars["extra_packages"] == ["git", "curl"]
        assert extra_vars["static_ip"] == "192.168.9.80/24"
        assert extra_vars["static_gw"] == "192.168.9.1"
        assert extra_vars["ad_domain"] == "broken.wrx"
        assert extra_vars["ad_realm"] == "BROKEN.WRX"
        assert extra_vars["ad_join_user"] == "jtd"
        assert extra_vars["default_storage"] == "bwrx"
        assert extra_vars["default_lxc_storage"] == "cephfs"
        assert extra_vars["default_bridge"] == "vmbr0"
        assert extra_vars["proxmox_api_host"] == "192.168.9.12"

        assert result == 0


def test_reconfigure_not_domain_joined_skips_password() -> None:
    """Test that reconfigure skips ensure_ad_password when not domain_joined."""
    with patch("pmx.reconfigure.load") as mock_load, \
         patch("pmx.reconfigure.find_by_name") as mock_find, \
         patch("pmx.reconfigure.ensure_ad_password") as mock_ad_password, \
         patch("pmx.reconfigure.run_playbook") as mock_playbook:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.default_node = "pve01"
        cfg.ad_domain = "broken.wrx"
        cfg.ad_realm = "BROKEN.WRX"
        cfg.ad_join_user = "jtd"
        cfg.default_storage = "bwrx"
        cfg.default_lxc_storage = "cephfs"
        cfg.default_bridge = "vmbr0"
        cfg.proxmox_api_host = "192.168.9.12"
        mock_load.return_value = cfg

        # State found but not domain_joined
        state = MagicMock()
        state.hostname = "testhost"
        state.vmid = 101
        state.kind = "lxc"
        state.os = "ubuntu"
        state.ip = "192.168.9.81"
        state.mac = "bb:cc:dd:ee:ff:aa"
        state.domain_joined = False
        state.cephfs_mounts = []
        state.rbd_disk = None
        state.extra_packages = []
        state.static_ip = None
        state.static_gw = None
        mock_find.return_value = state

        mock_playbook.return_value = 0

        result = run("testhost")

        # Verify ensure_ad_password was NOT called
        mock_ad_password.assert_not_called()

        # Verify playbook was called
        mock_playbook.assert_called_once()
        assert result == 0
