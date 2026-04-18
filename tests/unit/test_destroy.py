"""Tests for pmx/destroy.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pmx.destroy import _query_cluster, run


def test_destroy_missing_from_cluster_returns_1() -> None:
    """Test that destroying a guest not found on cluster returns 1."""
    with patch("pmx.destroy.load") as mock_load, \
         patch("pmx.destroy.find_by_name") as mock_find, \
         patch("pmx.destroy._query_cluster") as mock_query:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        mock_load.return_value = cfg
        mock_find.return_value = None
        mock_query.return_value = {}  # Empty cluster

        result = run("nonexistent", yes=True)

        assert result == 1


def test_destroy_state_missing_path_warns_and_continues() -> None:
    """Test that destroying a guest not in state log warns but continues."""
    with patch("pmx.destroy.load") as mock_load, \
         patch("pmx.destroy.find_by_name") as mock_find, \
         patch("pmx.destroy._query_cluster") as mock_query, \
         patch("pmx.destroy.run_playbook") as mock_playbook, \
         patch("pmx.destroy.click.echo") as mock_echo:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        cfg.default_node = "pve01"
        cfg.ad_domain = "broken.wrx"
        cfg.ad_join_user = "jtd"
        mock_load.return_value = cfg

        # State not found
        mock_find.return_value = None

        # But guest exists in cluster
        mock_query.return_value = {"test": (101, "vm")}
        mock_playbook.return_value = 0

        result = run("test", yes=True)

        # Check that warning was printed
        warning_calls = [call for call in mock_echo.call_args_list
                        if "not in" in str(call)]
        assert len(warning_calls) > 0

        # Should continue and call playbook
        assert mock_playbook.called
        assert result == 0


def test_query_cluster_parses_qm_and_pct_output() -> None:
    """Test that _query_cluster correctly parses qm and pct output."""
    ssh_output = """VMID NAME                 STATUS CORES MEMORY DISK
    101 ubuntu-vm            running    2 2048.0  32
    102 other-vm             stopped    1 1024.0  16
---
VMID STATUS LOCK NAME
    201 running      lxc-container
    202 stopped      another-lxc
"""

    with patch("pmx.destroy.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = ssh_output
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = _query_cluster("root@192.168.9.12")

        # Check VMs
        assert ("ubuntu-vm", (101, "vm")) in result.items()
        assert ("other-vm", (102, "vm")) in result.items()

        # Check LXCs
        assert ("lxc-container", (201, "lxc")) in result.items()
        assert ("another-lxc", (202, "lxc")) in result.items()

        assert len(result) == 4
