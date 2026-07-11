"""Tests for the DC-side deregistration vars threaded through pmx destroy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pmx.destroy import run


def _cfg(dc_ssh_host: str = "sysop@192.168.9.20") -> MagicMock:
    cfg = MagicMock()
    cfg.state_log_path = "/tmp/state.jsonl"
    cfg.proxmox_ssh_host = "root@192.168.9.12"
    cfg.default_node = "pve01"
    cfg.ad_domain = "broken.wrx"
    cfg.ad_realm = "BROKEN.WRX"
    cfg.ad_join_user = "jtd"
    cfg.dc_ssh_host = dc_ssh_host
    return cfg


def test_destroy_passes_dc_dereg_vars_to_playbook() -> None:
    """run() forwards dc_ssh_host + guest_ip + ad_domain so destroy.yml can run
    the DC-side dereg, targets the guest's actual node, and marks it domain-joined
    when a DC is configured."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
    ):
        mock_load.return_value = _cfg()

        state = MagicMock()
        state.ip = "192.168.9.45"
        state.domain_joined = True
        mock_find.return_value = state

        # Cluster reports apus as a VM on excelsior (not the default node).
        mock_query.return_value = {"apus": (102, "vm", "excelsior")}
        mock_playbook.return_value = 0

        result = run("apus", yes=True)

        assert result == 0
        mock_playbook.assert_called_once()
        playbook, extra_vars = mock_playbook.call_args[0]
        assert playbook == "destroy.yml"
        assert extra_vars["target_node"] == "excelsior"
        assert extra_vars["dc_ssh_host"] == "sysop@192.168.9.20"
        assert extra_vars["ad_domain"] == "broken.wrx"
        assert extra_vars["guest_ip"] == "192.168.9.45"
        assert extra_vars["guest_name"] == "apus"
        assert extra_vars["domain_join"] is True
        # No Kerberos password is prompted on destroy anymore.
        assert "ad_realm" not in extra_vars
        assert "ad_join_user" not in extra_vars


def test_destroy_without_dc_host_skips_dereg() -> None:
    """When dc_ssh_host is unset, domain_join is forced false so the DC-side play
    no-ops, while the Proxmox resource is still destroyed on its node."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy.query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
    ):
        mock_load.return_value = _cfg(dc_ssh_host="")

        state = MagicMock()
        state.ip = "192.168.9.45"
        state.domain_joined = True
        mock_find.return_value = state

        mock_query.return_value = {"apus": (102, "vm", "cerritos")}
        mock_playbook.return_value = 0

        result = run("apus", yes=True)

        assert result == 0
        _playbook, extra_vars = mock_playbook.call_args[0]
        assert extra_vars["target_node"] == "cerritos"
        assert extra_vars["domain_join"] is False
        assert extra_vars["dc_ssh_host"] == ""
