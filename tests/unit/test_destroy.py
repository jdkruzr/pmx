"""Tests for pmx/destroy.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pmx.destroy import run


def test_destroy_missing_from_cluster_returns_1() -> None:
    """Destroying a guest not found anywhere on the cluster returns 1."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
    ):
        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        mock_load.return_value = cfg
        mock_find.return_value = None
        mock_query.return_value = {}  # Empty cluster

        result = run("nonexistent", yes=True)

        assert result == 1


def test_destroy_state_missing_path_warns_and_continues() -> None:
    """A guest absent from the state log warns, still destroys, and targets the
    node the cluster reports it on."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
        patch("pmx.destroy.tombstone") as mock_tombstone,
        patch("pmx.destroy.click.echo") as mock_echo,
    ):
        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        cfg.default_node = "pve01"
        cfg.ad_domain = "broken.wrx"
        cfg.dc_ssh_host = "sysop@192.168.9.20"
        mock_load.return_value = cfg

        # State not found, but guest exists in the cluster on excelsior.
        mock_find.return_value = None
        mock_query.return_value = {"test": (101, "vm", "excelsior")}
        mock_playbook.return_value = 0
        mock_tombstone.return_value = None  # untracked guest has nothing to tombstone

        result = run("test", yes=True)

        warning_calls = [c for c in mock_echo.call_args_list if "not in" in str(c)]
        assert len(warning_calls) > 0

        assert mock_playbook.called
        _playbook, extra_vars = mock_playbook.call_args[0]
        assert extra_vars["target_node"] == "excelsior"
        # Not pmx-managed -> attempt dereg idempotently (dc_ssh_host is set).
        assert extra_vars["domain_join"] is True
        assert result == 0


def test_destroy_tombstones_on_success() -> None:
    """A clean teardown of a tracked guest tombstones it in the state log."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
        patch("pmx.destroy.tombstone") as mock_tombstone,
        patch("pmx.destroy.click.echo") as mock_echo,
    ):
        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        cfg.ad_domain = "broken.wrx"
        cfg.dc_ssh_host = "sysop@192.168.9.20"
        mock_load.return_value = cfg

        state = MagicMock()
        state.domain_joined = True
        state.ip = "192.168.9.95"
        mock_find.return_value = state
        mock_query.return_value = {"cumulus": (114, "vm", "cerritos")}
        mock_playbook.return_value = 0
        mock_tombstone.return_value = state  # a tombstone was written

        result = run("cumulus", yes=True)

        assert result == 0
        mock_tombstone.assert_called_once_with(cfg.state_log_path, "cumulus")
        marked = [c for c in mock_echo.call_args_list if "Marked cumulus destroyed" in str(c)]
        assert len(marked) == 1


def test_destroy_skips_tombstone_on_failure() -> None:
    """A failed teardown leaves the record live so a retry still sees it."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
        patch("pmx.destroy.tombstone") as mock_tombstone,
        patch("pmx.destroy.click.echo"),
    ):
        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        cfg.ad_domain = "broken.wrx"
        cfg.dc_ssh_host = "sysop@192.168.9.20"
        mock_load.return_value = cfg

        state = MagicMock()
        state.domain_joined = True
        state.ip = "192.168.9.95"
        mock_find.return_value = state
        mock_query.return_value = {"cumulus": (114, "vm", "cerritos")}
        mock_playbook.return_value = 2  # destroy failed

        result = run("cumulus", yes=True)

        assert result == 2
        mock_tombstone.assert_not_called()


def test_destroy_dry_run_reports_without_changes() -> None:
    """--dry-run prints the plan and touches nothing: no confirm, no playbook,
    no tombstone; it does inspect the DC read-only."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
        patch("pmx.destroy.tombstone") as mock_tombstone,
        patch("pmx.destroy._inspect_dc") as mock_inspect,
        patch("pmx.destroy._cluster_status") as mock_status,
        patch("pmx.destroy.click.echo") as mock_echo,
    ):
        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        cfg.ad_domain = "broken.wrx"
        cfg.dc_ssh_host = "sysop@192.168.9.20"
        mock_load.return_value = cfg

        mock_find.return_value = None  # untracked guest
        mock_query.return_value = {"paperless-ngx": (109, "vm", "kelvin")}
        mock_status.return_value = "running"
        mock_inspect.return_value = [
            "fwd A     : paperless-ngx.broken.wrx -> 192.168.9.53",
            "AD object : no match by dNSHostName or exact name -> destroy will NOT auto-remove",
        ]

        result = run("paperless-ngx", yes=False, dry_run=True)

        assert result == 0
        mock_playbook.assert_not_called()
        mock_tombstone.assert_not_called()
        mock_inspect.assert_called_once()
        joined = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "No changes made" in joined
        assert "will NOT auto-remove" in joined
        assert "untracked" in joined


def test_destroy_dry_run_non_domain_skips_dc_inspection() -> None:
    """A known non-domain guest's dry-run reports no DNS/AD work and never
    touches the DC."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
        patch("pmx.destroy.tombstone") as mock_tombstone,
        patch("pmx.destroy._inspect_dc") as mock_inspect,
        patch("pmx.destroy._cluster_status") as mock_status,
        patch("pmx.destroy.click.echo"),
    ):
        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        cfg.ad_domain = "broken.wrx"
        cfg.dc_ssh_host = "sysop@192.168.9.20"
        mock_load.return_value = cfg

        state = MagicMock()
        state.domain_joined = False
        state.ip = "192.168.9.81"
        mock_find.return_value = state
        mock_query.return_value = {"test-vm": (102, "vm", "cerritos")}
        mock_status.return_value = "running"

        result = run("test-vm", yes=False, dry_run=True)

        assert result == 0
        mock_inspect.assert_not_called()
        mock_playbook.assert_not_called()
        mock_tombstone.assert_not_called()
