"""Tests for pmx.cli module."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from pmx.cli import cmd_new
from pmx.translate import extra_vars_from


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


class TestCmdNew:
    """Test the cmd_new command."""

    @patch("pmx.credentials.ensure_ad_password")
    @patch("pmx.preflight.assert_name_available")
    @patch("pmx.ansible_runner.run_playbook")
    def test_dry_run_calls_run_playbook_with_dry_run(self, mock_run_playbook, mock_preflight, mock_ensure_ad):
        """--dry-run calls run_playbook with dry_run=True."""
        mock_run_playbook.return_value = 0

        runner = CliRunner()
        result = runner.invoke(
            cmd_new,
            [
                "--name", "test-vm",
                "--kind", "vm",
                "--os", "ubuntu",
                "--dry-run",
            ],
            env={"AD_JOIN_PASSWORD": "test"},
            catch_exceptions=False,
        )

        # Should exit with code 0 (not the NOT_IMPLEMENTED_EXIT of 1)
        assert result.exit_code == 0
        # Should call preflight check
        mock_preflight.assert_called_once()
        # Should call run_playbook with dry_run=True
        mock_run_playbook.assert_called_once()
        call_args = mock_run_playbook.call_args
        assert call_args[0][0] == "provision.yml"
        assert call_args[1]["dry_run"] is True

    @patch("pmx.credentials.ensure_ad_password")
    @patch("pmx.preflight.assert_name_available")
    @patch("pmx.ansible_runner.run_playbook")
    def test_without_dry_run_calls_playbook_for_vm(self, mock_run_playbook, mock_preflight, mock_ensure_ad):
        """Without --dry-run, calls run_playbook for VM creation."""
        mock_run_playbook.return_value = 0

        runner = CliRunner()
        result = runner.invoke(
            cmd_new,
            [
                "--name", "test-vm",
                "--kind", "vm",
                "--os", "ubuntu",
                "--no-domain",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        # Should call preflight check
        mock_preflight.assert_called_once()
        # Should call run_playbook without dry_run
        mock_run_playbook.assert_called_once()
        call_args = mock_run_playbook.call_args
        assert call_args[0][0] == "provision.yml"
        assert "dry_run" not in call_args[1] or call_args[1].get("dry_run") is False

    @patch("pmx.credentials.ensure_ad_password")
    def test_prompts_for_password_when_not_domain_false(self, mock_ensure_ad):
        """Calls ensure_ad_password when no_domain is False."""
        runner = CliRunner()
        runner.invoke(
            cmd_new,
            [
                "--name", "test-vm",
                "--kind", "vm",
                "--os", "ubuntu",
            ],
        )

        # Should call ensure_ad_password
        mock_ensure_ad.assert_called_once()

    @patch("pmx.credentials.ensure_ad_password")
    def test_skips_password_when_no_domain_true(self, mock_ensure_ad):
        """Does not call ensure_ad_password when --no-domain is set."""
        runner = CliRunner()
        runner.invoke(
            cmd_new,
            [
                "--name", "test-vm",
                "--kind", "vm",
                "--os", "ubuntu",
                "--no-domain",
            ],
        )

        # Should NOT call ensure_ad_password
        mock_ensure_ad.assert_not_called()

    @patch("pmx.credentials.ensure_ad_password")
    @patch("pmx.ansible_runner.run_playbook")
    def test_dry_run_with_all_options(self, mock_run_playbook, mock_ensure_ad):
        """--dry-run includes all options in extra-vars."""
        mock_run_playbook.return_value = 0

        runner = CliRunner()
        result = runner.invoke(
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
        call_args = mock_run_playbook.call_args
        extra_vars = call_args[0][1]

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

    @patch("pmx.credentials.ensure_ad_password")
    def test_rbd_disk_rejects_lxc(self, mock_ensure_ad):
        """--rbd-disk with --kind lxc exits 2 with VM-only error."""
        runner = CliRunner()
        result = runner.invoke(
            cmd_new,
            [
                "--name", "test-lxc",
                "--kind", "lxc",
                "--os", "ubuntu",
                "--rbd-disk", "10",
                "--no-domain",
            ],
        )

        assert result.exit_code == 2
        assert "VM-only" in result.output

    @patch("pmx.credentials.ensure_ad_password")
    @patch("pmx.preflight.assert_name_available")
    @patch("pmx.ansible_runner.run_playbook")
    def test_rbd_disk_accepts_vm_dry_run(self, mock_run_playbook, mock_preflight, mock_ensure_ad):
        """--rbd-disk with --kind vm on --dry-run exits 0."""
        mock_run_playbook.return_value = 0

        runner = CliRunner()
        result = runner.invoke(
            cmd_new,
            [
                "--name", "test-vm",
                "--kind", "vm",
                "--os", "ubuntu",
                "--rbd-disk", "10",
                "--no-domain",
                "--dry-run",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        call_args = mock_run_playbook.call_args
        extra_vars = call_args[0][1]
        assert extra_vars["rbd_disk"] == 10

    @patch("pmx.credentials.ensure_ad_password")
    @patch("pmx.preflight.assert_name_available")
    @patch("pmx.ansible_runner.run_playbook")
    def test_static_gw_included_in_dry_run(self, mock_run_playbook, mock_preflight, mock_ensure_ad):
        """--static-gw is included in extra-vars during dry-run."""
        mock_run_playbook.return_value = 0

        runner = CliRunner()
        result = runner.invoke(
            cmd_new,
            [
                "--name", "test-vm",
                "--kind", "vm",
                "--os", "ubuntu",
                "--static-ip", "192.168.9.80/24",
                "--static-gw", "192.168.9.1",
                "--no-domain",
                "--dry-run",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        call_args = mock_run_playbook.call_args
        extra_vars = call_args[0][1]
        assert extra_vars["static_gw"] == "192.168.9.1"
