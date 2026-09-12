"""Tests for pmx.preflight IP-availability checks (assert_ip_available + helpers)."""

from __future__ import annotations

from unittest.mock import MagicMock

import click
import pytest

from pmx.config import Config
from pmx.preflight import (
    _parse_allocated_ips,
    _suggest_free_ip,
    assert_ip_available,
)


def _make_cfg() -> Config:
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


class TestParseAllocatedIps:
    def test_empty(self) -> None:
        assert _parse_allocated_ips("") == set()

    def test_vm_ipconfig(self) -> None:
        text = "name: neptune\nipconfig0: ip=192.168.9.52/24,gw=192.168.9.1\n"
        assert _parse_allocated_ips(text) == {"192.168.9.52"}

    def test_lxc_net0(self) -> None:
        text = (
            "hostname: ct1\n"
            "net0: name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:00:01,"
            "ip=192.168.9.60/24,gw=192.168.9.1\n"
        )
        assert _parse_allocated_ips(text) == {"192.168.9.60"}

    def test_dhcp_yields_nothing(self) -> None:
        assert _parse_allocated_ips("ipconfig0: ip=dhcp\n") == set()

    def test_gateway_token_not_captured(self) -> None:
        # Only the ip= token is read, never gw=.
        result = _parse_allocated_ips("ipconfig0: ip=192.168.9.52/24,gw=192.168.9.1\n")
        assert result == {"192.168.9.52"}

    def test_unrelated_lines_ignored(self) -> None:
        text = "name: x\nmemory: 2048\nnameserver: 192.168.9.20\n"
        assert _parse_allocated_ips(text) == set()

    def test_multiple_guests(self) -> None:
        text = (
            "ipconfig0: ip=192.168.9.52/24,gw=192.168.9.1\n"
            "net0: name=eth0,ip=192.168.9.60/24\n"
            "ipconfig0: ip=dhcp\n"
        )
        assert _parse_allocated_ips(text) == {"192.168.9.52", "192.168.9.60"}


class TestSuggestFreeIp:
    def test_lowest_free_skips_gateway(self) -> None:
        # .1 is the conventional gateway and is skipped; .2 is the first offer.
        assert _suggest_free_ip("192.168.9.52/24", {"192.168.9.52"}) == "192.168.9.2"

    def test_skips_allocated(self) -> None:
        taken = {"192.168.9.2", "192.168.9.3"}
        assert _suggest_free_ip("192.168.9.50/24", taken) == "192.168.9.4"

    def test_none_when_full(self) -> None:
        # /30 usable hosts are .1 and .2; .1 (gateway) skipped, .2 taken -> nothing free.
        assert _suggest_free_ip("192.168.9.2/30", {"192.168.9.2"}) is None


class TestAssertIpAvailable:
    def test_skips_when_dhcp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)
        assert_ip_available(_make_cfg(), None)
        assert mock_run.call_count == 0

    def test_passes_when_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        mock_run = MagicMock()
        mock_run.return_value.stdout = "ipconfig0: ip=192.168.9.52/24,gw=192.168.9.1\n"
        monkeypatch.setattr(subprocess, "run", mock_run)
        assert_ip_available(_make_cfg(), "192.168.9.80/24")  # .80 is free
        assert mock_run.call_count == 1

    def test_aborts_when_taken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        mock_run = MagicMock()
        mock_run.return_value.stdout = "ipconfig0: ip=192.168.9.52/24,gw=192.168.9.1\n"
        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(click.Abort):
            assert_ip_available(_make_cfg(), "192.168.9.52/24")

    def test_aborts_on_network_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(click.Abort):
            assert_ip_available(_make_cfg(), "192.168.9.0/24")
        assert mock_run.call_count == 0  # rejected before any SSH

    def test_aborts_on_broadcast_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(click.Abort):
            assert_ip_available(_make_cfg(), "192.168.9.255/24")
        assert mock_run.call_count == 0

    def test_aborts_on_ssh_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        mock_run = MagicMock()
        mock_run.side_effect = subprocess.CalledProcessError(1, "ssh")
        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(click.Abort):
            assert_ip_available(_make_cfg(), "192.168.9.80/24")

    def test_aborts_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        mock_run = MagicMock()
        mock_run.side_effect = subprocess.TimeoutExpired("ssh", 15)
        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(click.Abort):
            assert_ip_available(_make_cfg(), "192.168.9.80/24")
