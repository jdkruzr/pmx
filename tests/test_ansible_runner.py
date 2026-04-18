"""Tests for pmx.ansible_runner module."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from pmx.ansible_runner import run_playbook


class TestRunPlaybook:
    """Test suite for run_playbook function."""

    def test_playbook_not_found(self):
        """Returns exit code 2 when playbook does not exist."""
        result = run_playbook("nonexistent.yml", {})
        assert result == 2

    def test_dry_run_returns_zero(self, capsys):
        """Dry run returns exit code 0 and prints the command."""
        extra_vars = {"guest_name": "test-vm", "guest_kind": "vm"}
        result = run_playbook("provision.yml", extra_vars, dry_run=True)

        assert result == 0
        captured = capsys.readouterr()
        assert "ansible-playbook" in captured.err
        assert "provision.yml" in captured.err
        assert json.dumps(extra_vars) in captured.err

    @patch("pmx.ansible_runner.subprocess.run")
    def test_run_playbook_calls_subprocess(self, mock_run):
        """Calls subprocess.run with correct command and environment."""
        mock_run.return_value = MagicMock(returncode=0)

        extra_vars = {"guest_name": "test-vm"}
        run_playbook("provision.yml", extra_vars, dry_run=False)

        # Verify subprocess.run was called
        assert mock_run.called
        call_args = mock_run.call_args

        # Check command includes ansible-playbook and extra-vars
        cmd = call_args[0][0]
        assert "ansible-playbook" in cmd
        assert "-e" in cmd

        # Check environment is inherited
        assert call_args[1]["env"] == os.environ.copy()

    @patch("pmx.ansible_runner.subprocess.run")
    def test_run_playbook_returns_subprocess_exit_code(self, mock_run):
        """Returns the exit code from subprocess.run."""
        mock_run.return_value = MagicMock(returncode=42)

        result = run_playbook("provision.yml", {}, dry_run=False)

        assert result == 42

    @patch("pmx.ansible_runner.subprocess.run")
    def test_run_playbook_inherits_environment(self, mock_run):
        """Subprocess inherits the current process environment."""
        mock_run.return_value = MagicMock(returncode=0)

        # Set a test environment variable
        test_env_var = "TEST_AD_PASSWORD"
        test_value = "test_password_123"
        original_value = os.environ.get(test_env_var)

        try:
            os.environ[test_env_var] = test_value
            run_playbook("provision.yml", {}, dry_run=False)

            # Verify the environment passed to subprocess includes the variable
            env_passed = mock_run.call_args[1]["env"]
            assert env_passed[test_env_var] == test_value
        finally:
            if original_value is not None:
                os.environ[test_env_var] = original_value
            else:
                os.environ.pop(test_env_var, None)

    def test_ansible_dir_is_repo_root_ansible(self):
        """ANSIBLE_DIR should point to ansible directory in repo root."""
        from pmx.ansible_runner import ANSIBLE_DIR, REPO_ROOT

        assert ANSIBLE_DIR == REPO_ROOT / "ansible"
        assert ANSIBLE_DIR.exists()

    def test_repo_root_resolves_correctly(self):
        """REPO_ROOT should resolve to parent of pmx package."""
        from pmx.ansible_runner import REPO_ROOT

        # REPO_ROOT should be two directories up from the module
        assert (REPO_ROOT / "pmx").is_dir()
        assert (REPO_ROOT / "ansible").is_dir()
