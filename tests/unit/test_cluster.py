"""Tests for pmx/cluster.py."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import click
import pytest

from pmx.cluster import query_cluster


def test_query_cluster_parses_pvesh_json() -> None:
    """query_cluster parses pvesh /cluster/resources JSON into
    name -> (vmid, kind, node), mapping qemu->vm and lxc->lxc, ignoring non-guests."""
    pvesh_json = json.dumps(
        [
            {"name": "ubuntu-vm", "vmid": 101, "node": "cerritos", "type": "qemu"},
            {"name": "other-vm", "vmid": 102, "node": "excelsior", "type": "qemu"},
            {"name": "lxc-container", "vmid": 201, "node": "kelvin", "type": "lxc"},
            {"id": "storage/cephfs", "type": "storage"},  # non-guest, must be ignored
        ]
    )

    with patch("pmx.cluster.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = pvesh_json
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = query_cluster("root@192.168.9.12")

        assert result["ubuntu-vm"] == (101, "vm", "cerritos")
        assert result["other-vm"] == (102, "vm", "excelsior")
        assert result["lxc-container"] == (201, "lxc", "kelvin")
        assert len(result) == 3  # storage entry ignored


def test_query_cluster_empty_output() -> None:
    """No guests / empty stdout yields an empty map, not a crash."""
    with patch("pmx.cluster.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        assert query_cluster("root@192.168.9.12") == {}


def test_query_cluster_ssh_failure_aborts() -> None:
    """A failed ssh/pvesh call aborts rather than returning a partial map."""
    with patch("pmx.cluster.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=255, cmd="ssh", stderr="connection refused"
        )
        with pytest.raises(click.Abort):
            query_cluster("root@192.168.9.12")


def test_query_cluster_timeout_aborts() -> None:
    """A hung Proxmox query aborts on timeout."""
    with patch("pmx.cluster.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=20)
        with pytest.raises(click.Abort):
            query_cluster("root@192.168.9.12")


def test_query_cluster_bad_json_aborts() -> None:
    """Unparseable pvesh output aborts rather than silently dropping guests."""
    with patch("pmx.cluster.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "not json {"
        mock_run.return_value = mock_result
        with pytest.raises(click.Abort):
            query_cluster("root@192.168.9.12")
