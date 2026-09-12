"""Tests for pmx.preflight — name uniqueness (cluster-wide) and CephX entity availability."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import click
import pytest

from pmx.config import Config
from pmx.preflight import assert_cephx_entity_available, assert_name_available


def _cfg() -> Config:
    return Config(
        proxmox_ssh_host="root@192.168.9.12",
        proxmox_api_host="192.168.9.12",
        default_node="pve01",
        default_storage="bwrx",
        default_lxc_storage="cephfs",
        default_bridge="vmbr0",
        ad_domain="broken.wrx",
        ad_realm="BROKEN.WRX",
        ad_join_user="jtd",
        ceph_mons=["192.168.9.11"],
        state_log_path="state/guests.jsonl",
    )


_CLUSTER = {
    "neptune": (112, "vm", "cerritos"),
    "aurora": (120, "lxc", "kelvin"),
}


class TestAssertNameAvailable:
    """Tests for assert_name_available — cluster-wide name uniqueness."""

    def test_assert_name_available_when_name_not_exists(self) -> None:
        """Given name not in cluster, assert_name_available returns normally."""
        with patch("pmx.preflight.query_cluster", return_value=_CLUSTER):
            assert_name_available(_cfg(), "newhost")

    def test_assert_name_available_raises_when_name_exists(self) -> None:
        """Given name already in cluster (on any node), raises click.Abort."""
        with patch("pmx.preflight.query_cluster", return_value=_CLUSTER):
            with pytest.raises(click.Abort):
                assert_name_available(_cfg(), "neptune")
            with pytest.raises(click.Abort):
                assert_name_available(_cfg(), "aurora")  # an LXC on another node

    def test_assert_name_available_propagates_cluster_query_abort(self) -> None:
        """query_cluster aborts itself on ssh failure/timeout; that propagates."""
        with patch("pmx.preflight.query_cluster", side_effect=click.Abort()), \
             pytest.raises(click.Abort):
            assert_name_available(_cfg(), "newhost")

    def test_assert_name_available_rejects_invalid_names(self) -> None:
        """Invalid names abort before any cluster query."""
        with patch("pmx.preflight.query_cluster") as mock_query:
            for invalid_name in ["-invalid", "name_underscore", "name with spaces", "name.dot", ""]:
                with pytest.raises(click.Abort):
                    assert_name_available(_cfg(), invalid_name)
            assert mock_query.call_count == 0

    def test_assert_name_available_rejects_reserved_ceph_names(self) -> None:
        """Names that would mint client.admin / client.crash / client.bootstrap-* abort
        before any cluster query."""
        with patch("pmx.preflight.query_cluster") as mock_query:
            for reserved in ["admin", "crash", "bootstrap-osd", "bootstrap-rgw"]:
                with pytest.raises(click.Abort):
                    assert_name_available(_cfg(), reserved)
            assert mock_query.call_count == 0

    def test_assert_name_available_accepts_valid_names(self) -> None:
        with patch("pmx.preflight.query_cluster", return_value={}):
            for valid_name in ["myhost", "test-vm-01", "a", "ABC123", "host1-2-3"]:
                assert_name_available(_cfg(), valid_name)

    def test_assert_name_available_uses_cluster_wide_query(self) -> None:
        """Uniqueness is judged cluster-wide via pvesh, not a node-local qm/pct list."""
        cfg = _cfg()
        with patch("pmx.preflight.query_cluster", return_value={}) as mock_query:
            assert_name_available(cfg, "testhost")
        mock_query.assert_called_once_with(cfg.proxmox_ssh_host)


class TestAssertCephxEntityAvailable:
    """Tests for assert_cephx_entity_available — `client.<name>` must not pre-exist."""

    def test_absent_entity_passes(self) -> None:
        """`ceph auth get` exits 2 (ENOENT) when the entity is free."""
        result = MagicMock(returncode=2, stderr="")
        with patch("pmx.preflight.subprocess.run", return_value=result) as mock_run:
            assert_cephx_entity_available(_cfg(), "newhost")
        cmd = mock_run.call_args[0][0]
        assert "root@192.168.9.12" in cmd
        assert "BatchMode=yes" in cmd
        assert any("ceph auth get client.newhost" in part for part in cmd)

    def test_existing_entity_aborts(self, capsys) -> None:
        result = MagicMock(returncode=0, stderr="")
        with patch("pmx.preflight.subprocess.run", return_value=result), \
             pytest.raises(click.Abort):
            assert_cephx_entity_available(_cfg(), "neptune")
        assert "client.neptune already exists" in capsys.readouterr().err

    def test_transport_failure_aborts(self) -> None:
        """Any rc other than 0/2 (e.g. ssh's 255) is a failed query, not a free name."""
        result = MagicMock(returncode=255, stderr="Connection refused")
        with patch("pmx.preflight.subprocess.run", return_value=result), \
             pytest.raises(click.Abort):
            assert_cephx_entity_available(_cfg(), "newhost")

    def test_timeout_aborts(self) -> None:
        with patch(
            "pmx.preflight.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ssh", 15),
        ), pytest.raises(click.Abort):
            assert_cephx_entity_available(_cfg(), "newhost")
