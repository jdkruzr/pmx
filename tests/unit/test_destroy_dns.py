"""Tests for the DNS-deregister extra-vars threaded through pmx destroy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pmx.destroy import run


def test_destroy_passes_dns_dereg_vars_to_playbook() -> None:
    """run() forwards ad_realm + guest_ip + domain_join so destroy.yml can
    deregister the guest's DNS A/PTR from the DC."""
    with (
        patch("pmx.destroy.load") as mock_load,
        patch("pmx.destroy.find_by_name") as mock_find,
        patch("pmx.destroy._query_cluster") as mock_query,
        patch("pmx.destroy.run_playbook") as mock_playbook,
        patch("pmx.destroy.ensure_ad_password"),
    ):
        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        cfg.default_node = "pve01"
        cfg.ad_domain = "broken.wrx"
        cfg.ad_realm = "BROKEN.WRX"
        cfg.ad_join_user = "jtd"
        mock_load.return_value = cfg

        state = MagicMock()
        state.ip = "192.168.9.45"
        state.domain_joined = True
        mock_find.return_value = state

        mock_query.return_value = {"apus": (102, "vm")}
        mock_playbook.return_value = 0

        result = run("apus", yes=True)

        assert result == 0
        mock_playbook.assert_called_once()
        playbook, extra_vars = mock_playbook.call_args[0]
        assert playbook == "destroy.yml"
        assert extra_vars["ad_realm"] == "BROKEN.WRX"
        assert extra_vars["ad_domain"] == "broken.wrx"
        assert extra_vars["guest_ip"] == "192.168.9.45"
        assert extra_vars["guest_name"] == "apus"
        assert extra_vars["domain_join"] is True
