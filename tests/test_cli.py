"""Tests for pmx.cli module."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from pmx.cli import cmd_new
from pmx.config import Config
from pmx.translate import extra_vars_from


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
        ceph_mons=["192.168.9.11", "192.168.9.12"],
        state_log_path="state/guests.jsonl",
        dc_ssh_host="sysop@192.168.9.20",
    )


class TestExtraVarsFrom:
    """Test the extra_vars_from helper function."""

    def test_basic_conversion(self):
        """Converts click kwargs to ansible extra-vars contract."""
        kwargs = {
            "name": "test-vm",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 4,
            "memory": 4096,
            "disk": 64,
            "cephfs": [],
            "rbd_disk": None,
            "extra_packages": "",
            "static_ip": None,
            "static_gw": None,
            "no_domain": False,
            "dry_run": False,
        }
        result = extra_vars_from(kwargs)

        assert result["guest_name"] == "test-vm"
        assert result["guest_kind"] == "vm"
        assert result["guest_os"] == "ubuntu"
        assert result["cores"] == 4
        assert result["memory"] == 4096
        assert result["disk"] == 64
        assert result["cephfs_mounts"] == []
        assert result["rbd_disk"] is None
        assert result["extra_packages"] == []
        assert result["static_ip"] is None
        assert result["static_gw"] is None
        assert result["domain_join"] is True

    def test_domain_join_false_when_no_domain_flag(self):
        """Sets domain_join to False when no_domain flag is True."""
        kwargs = {
            "name": "test",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 2,
            "memory": 2048,
            "disk": 32,
            "cephfs": [],
            "rbd_disk": None,
            "extra_packages": "",
            "static_ip": None,
            "static_gw": None,
            "no_domain": True,
            "dry_run": False,
        }
        result = extra_vars_from(kwargs)
        assert result["domain_join"] is False

    def test_cephfs_mounts_conversion(self):
        """Converts cephfs tuple to list."""
        kwargs = {
            "name": "test",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 2,
            "memory": 2048,
            "disk": 32,
            "cephfs": ("subpath1:/mnt1", "subpath2:/mnt2"),
            "rbd_disk": None,
            "extra_packages": "",
            "static_ip": None,
            "static_gw": None,
            "no_domain": False,
            "dry_run": False,
        }
        result = extra_vars_from(kwargs)
        assert result["cephfs_mounts"] == ["subpath1:/mnt1", "subpath2:/mnt2"]

    def test_extra_packages_comma_separated(self):
        """Converts comma-separated extra_packages string to list."""
        kwargs = {
            "name": "test",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 2,
            "memory": 2048,
            "disk": 32,
            "cephfs": [],
            "rbd_disk": None,
            "extra_packages": "curl,git,vim",
            "static_ip": None,
            "static_gw": None,
            "no_domain": False,
            "dry_run": False,
        }
        result = extra_vars_from(kwargs)
        assert result["extra_packages"] == ["curl", "git", "vim"]

    def test_extra_packages_empty_string(self):
        """Handles empty extra_packages string."""
        kwargs = {
            "name": "test",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 2,
            "memory": 2048,
            "disk": 32,
            "cephfs": [],
            "rbd_disk": None,
            "extra_packages": "",
            "static_ip": None,
            "static_gw": None,
            "no_domain": False,
            "dry_run": False,
        }
        result = extra_vars_from(kwargs)
        assert result["extra_packages"] == []

    def test_static_ip_preserved(self):
        """Preserves static_ip if provided."""
        kwargs = {
            "name": "test",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 2,
            "memory": 2048,
            "disk": 32,
            "cephfs": [],
            "rbd_disk": None,
            "extra_packages": "",
            "static_ip": "192.168.9.80/24",
            "no_domain": False,
            "dry_run": False,
            "static_gw": None,
        }
        result = extra_vars_from(kwargs)
        assert result["static_ip"] == "192.168.9.80/24"

    def test_static_gw_included_in_output(self):
        """Includes static_gw in the output."""
        kwargs = {
            "name": "test",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 2,
            "memory": 2048,
            "disk": 32,
            "cephfs": [],
            "rbd_disk": None,
            "extra_packages": "",
            "static_ip": "192.168.9.80/24",
            "static_gw": "192.168.9.1",
            "no_domain": False,
            "dry_run": False,
        }
        result = extra_vars_from(kwargs)
        assert result["static_gw"] == "192.168.9.1"

    def test_static_gw_none_when_not_provided(self):
        """Handles static_gw as None when not provided."""
        kwargs = {
            "name": "test",
            "kind": "vm",
            "os_family": "ubuntu",
            "cores": 2,
            "memory": 2048,
            "disk": 32,
            "cephfs": [],
            "rbd_disk": None,
            "extra_packages": "",
            "static_ip": None,
            "static_gw": None,
            "no_domain": False,
            "dry_run": False,
        }
        result = extra_vars_from(kwargs)
        assert result["static_gw"] is None


# cmd_new imports its collaborators lazily, so patch them where they live. The
# config loader is patched too: these tests must not depend on the developer's
# ~/.config/pmx/config.yml or on ssh reachability of the cluster.
_PATCHES = (
    "pmx.config.load",
    "pmx.credentials.ensure_ad_password",
    "pmx.preflight.assert_name_available",
    "pmx.preflight.assert_ip_available",
    "pmx.preflight.assert_cephx_entity_available",
    "pmx.ansible_runner.run_playbook",
)


def _patched(func):
    """Apply _PATCHES so the test receives mocks in _PATCHES order.

    Stacked @patch decorators hand the innermost mock first; applying the
    first target first makes it innermost, hence first argument.
    """
    for target in _PATCHES:
        func = patch(target)(func)
    return func


class TestCmdNew:
    """Test the cmd_new command."""

    @_patched
    def test_dry_run_calls_run_playbook_with_dry_run(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """--dry-run calls run_playbook with dry_run=True."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        result = CliRunner().invoke(
            cmd_new,
            ["--name", "test-vm", "--kind", "vm", "--os", "ubuntu", "--dry-run"],
            env={"AD_JOIN_PASSWORD": "test"},
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        mock_name.assert_called_once()
        mock_run_playbook.assert_called_once()
        call_args = mock_run_playbook.call_args
        assert call_args[0][0] == "provision.yml"
        assert call_args[1]["dry_run"] is True

    @_patched
    def test_without_dry_run_calls_playbook_for_vm(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """Without --dry-run, calls run_playbook for VM creation."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        result = CliRunner().invoke(
            cmd_new,
            ["--name", "test-vm", "--kind", "vm", "--os", "ubuntu", "--no-domain"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        mock_name.assert_called_once()
        mock_run_playbook.assert_called_once()
        call_args = mock_run_playbook.call_args
        assert call_args[0][0] == "provision.yml"
        assert "dry_run" not in call_args[1] or call_args[1].get("dry_run") is False

    @_patched
    def test_prompts_for_password_when_not_domain_false(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """Calls ensure_ad_password when no_domain is False."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        CliRunner().invoke(cmd_new, ["--name", "test-vm", "--kind", "vm", "--os", "ubuntu"])

        mock_ensure_ad.assert_called_once()

    @_patched
    def test_skips_password_when_no_domain_true(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """Does not call ensure_ad_password when --no-domain is set."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        CliRunner().invoke(
            cmd_new, ["--name", "test-vm", "--kind", "vm", "--os", "ubuntu", "--no-domain"]
        )

        mock_ensure_ad.assert_not_called()

    @_patched
    def test_dry_run_with_all_options(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """--dry-run includes all options in extra-vars."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        result = CliRunner().invoke(
            cmd_new,
            [
                "--name", "complex-vm",
                "--kind", "vm",
                "--os", "rocky",
                "--cores", "8",
                "--memory", "8192",
                "--disk", "100",
                "--cephfs", "cephfs1:/mnt1",
                "--cephfs", "cephfs2:/mnt2",
                "--rbd-disk", "500",
                "--extra-packages", "curl,git",
                "--static-ip", "192.168.9.100/24",
                "--dry-run",
            ],
            env={"AD_JOIN_PASSWORD": "test"},
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        extra_vars = mock_run_playbook.call_args[0][1]

        assert extra_vars["guest_name"] == "complex-vm"
        assert extra_vars["guest_kind"] == "vm"
        assert extra_vars["guest_os"] == "rocky"
        assert extra_vars["cores"] == 8
        assert extra_vars["memory"] == 8192
        assert extra_vars["disk"] == 100
        assert extra_vars["cephfs_mounts"] == ["cephfs1:/mnt1", "cephfs2:/mnt2"]
        assert extra_vars["rbd_disk"] == 500
        assert extra_vars["extra_packages"] == ["curl", "git"]
        assert extra_vars["static_ip"] == "192.168.9.100/24"
        assert extra_vars["domain_join"] is True
        # The workstation is not a Ceph client: no secret/conf paths go to Ansible;
        # the per-guest key type does.
        assert "ceph_secret_path" not in extra_vars
        assert "ceph_conf_path" not in extra_vars
        assert extra_vars["ceph_mons"] == ["192.168.9.11", "192.168.9.12"]
        assert extra_vars["cephx_key_type"] == "aes"
        assert extra_vars["dc_ssh_host"] == "sysop@192.168.9.20"

    @_patched
    def test_cephfs_triggers_entity_preflight(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """--cephfs makes `new` check that client.<name> is free; without it, no check."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        CliRunner().invoke(
            cmd_new,
            ["--name", "fsguest", "--kind", "vm", "--os", "ubuntu", "--no-domain",
             "--cephfs", "supernote:/mnt/sn", "--dry-run"],
            catch_exceptions=False,
        )
        mock_entity.assert_called_once()
        assert mock_entity.call_args[0][1] == "fsguest"

        mock_entity.reset_mock()
        CliRunner().invoke(
            cmd_new,
            ["--name", "plain", "--kind", "vm", "--os", "ubuntu", "--no-domain", "--dry-run"],
            catch_exceptions=False,
        )
        mock_entity.assert_not_called()

    @_patched
    def test_rbd_disk_rejects_lxc(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """--rbd-disk with --kind lxc exits 2 with VM-only error."""
        mock_load.return_value = _cfg()

        result = CliRunner().invoke(
            cmd_new,
            ["--name", "test-lxc", "--kind", "lxc", "--os", "ubuntu", "--rbd-disk", "10",
             "--no-domain"],
        )

        assert result.exit_code == 2
        assert "VM-only" in result.output
        mock_run_playbook.assert_not_called()

    @_patched
    def test_rbd_disk_accepts_vm_dry_run(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """--rbd-disk with --kind vm on --dry-run exits 0."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        result = CliRunner().invoke(
            cmd_new,
            ["--name", "test-vm", "--kind", "vm", "--os", "ubuntu", "--rbd-disk", "10",
             "--no-domain", "--dry-run"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert mock_run_playbook.call_args[0][1]["rbd_disk"] == 10

    @_patched
    def test_static_gw_included_in_dry_run(
        self, mock_load, mock_ensure_ad, mock_name, mock_ip, mock_entity, mock_run_playbook
    ):
        """--static-gw is included in extra-vars during dry-run."""
        mock_load.return_value = _cfg()
        mock_run_playbook.return_value = 0

        result = CliRunner().invoke(
            cmd_new,
            ["--name", "test-vm", "--kind", "vm", "--os", "ubuntu",
             "--static-ip", "192.168.9.80/24", "--static-gw", "192.168.9.1",
             "--no-domain", "--dry-run"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert mock_run_playbook.call_args[0][1]["static_gw"] == "192.168.9.1"
