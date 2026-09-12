"""Tests for pmx.config module."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.exceptions import Abort

from pmx.config import Config, load

_VALID_CONFIG = """proxmox_ssh_host: root@192.168.9.12
proxmox_api_host: 192.168.9.12
default_node: pve01
default_storage: bwrx
default_lxc_storage: cephfs
default_bridge: vmbr0
ad_domain: broken.wrx
ad_realm: BROKEN.WRX
ad_join_user: jtd
ceph_mons:
  - 192.168.9.11
  - 192.168.9.12
state_log_path: state/guests.jsonl
"""


class TestConfigLoad:
    """Test the load function for config loading."""

    def test_raises_abort_when_file_missing(self, monkeypatch):
        """Raises click.Abort when config file does not exist."""
        nonexistent_path = Path("/nonexistent/path/config.yml")
        monkeypatch.setattr("pmx.config.CONFIG_PATH", nonexistent_path)

        with pytest.raises(Abort):
            load()

    def test_raises_abort_on_malformed_yaml_missing_required_fields(self, tmp_path, monkeypatch, capsys):
        """Raises click.Abort when YAML is malformed or missing required fields."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("invalid: field\n")

        monkeypatch.setattr("pmx.config.CONFIG_PATH", config_file)

        with pytest.raises(Abort):
            load()

        captured = capsys.readouterr()
        assert "malformed" in captured.err

    def test_returns_populated_config_on_happy_path(self, tmp_path, monkeypatch):
        """Returns populated Config object when valid config file exists."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(_VALID_CONFIG)

        monkeypatch.setattr("pmx.config.CONFIG_PATH", config_file)

        config = load()

        assert isinstance(config, Config)
        assert config.proxmox_ssh_host == "root@192.168.9.12"
        assert config.proxmox_api_host == "192.168.9.12"
        assert config.default_node == "pve01"
        assert config.default_storage == "bwrx"
        assert config.default_lxc_storage == "cephfs"
        assert config.default_bridge == "vmbr0"
        assert config.ad_domain == "broken.wrx"
        assert config.ad_realm == "BROKEN.WRX"
        assert config.ad_join_user == "jtd"
        assert config.ceph_mons == ["192.168.9.11", "192.168.9.12"]
        assert config.state_log_path == "state/guests.jsonl"

    def test_cephx_key_type_defaults_to_aes(self, tmp_path, monkeypatch):
        """cephx_key_type is optional and defaults to aes (what 6.8 guest kernels speak)."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(_VALID_CONFIG)
        monkeypatch.setattr("pmx.config.CONFIG_PATH", config_file)

        assert load().cephx_key_type == "aes"

    def test_cephx_key_type_can_be_set(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yml"
        config_file.write_text(_VALID_CONFIG + "cephx_key_type: aes256k\n")
        monkeypatch.setattr("pmx.config.CONFIG_PATH", config_file)

        assert load().cephx_key_type == "aes256k"

    def test_removed_ceph_keys_abort_with_hint(self, tmp_path, monkeypatch, capsys):
        """A config still carrying the old workstation-Ceph-client keys is refused,
        with a message that says why, rather than silently ignored."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            _VALID_CONFIG
            + "ceph_conf_path: /etc/ceph/ceph.conf\nceph_secret_path: /etc/ceph/cephfs.secret\n"
        )
        monkeypatch.setattr("pmx.config.CONFIG_PATH", config_file)

        with pytest.raises(Abort):
            load()

        err = capsys.readouterr().err
        assert "obsolete keys" in err
        assert "ceph_conf_path" in err
        assert "ceph_secret_path" in err

    def test_config_is_frozen_dataclass(self, tmp_path, monkeypatch):
        """Config is a frozen dataclass (immutable)."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(_VALID_CONFIG)

        monkeypatch.setattr("pmx.config.CONFIG_PATH", config_file)
        config = load()

        # Frozen dataclass should raise error on attribute assignment
        with pytest.raises((AttributeError, TypeError)):
            config.ad_domain = "different.wrx"
