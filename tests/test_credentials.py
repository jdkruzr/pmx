"""Tests for pmx.credentials module."""

from __future__ import annotations

import os

import pytest
from click.exceptions import Abort

from pmx.credentials import ensure_ad_password, ENV_VAR


class TestEnsureAdPassword:
    """Test the ensure_ad_password function."""

    def test_returns_cached_value_when_env_var_set(self):
        """Returns cached value without prompting when env var already set."""
        test_password = "cached_password_123"
        os.environ[ENV_VAR] = test_password

        try:
            result = ensure_ad_password()
            assert result == test_password
        finally:
            os.environ.pop(ENV_VAR, None)

    def test_prompts_via_getpass_when_env_var_unset(self, monkeypatch, capsys):
        """Prompts via getpass when env var is unset, caches in os.environ."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr("getpass.getpass", lambda prompt: "new_password_456")

        result = ensure_ad_password()

        assert result == "new_password_456"
        assert os.environ[ENV_VAR] == "new_password_456"

        # Clean up
        os.environ.pop(ENV_VAR, None)

    def test_raises_abort_on_empty_input(self, monkeypatch, capsys):
        """Raises click.Abort when user provides empty input."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr("getpass.getpass", lambda prompt: "")

        with pytest.raises(Abort):
            ensure_ad_password()

        captured = capsys.readouterr()
        assert "No password entered" in captured.err

    def test_caches_password_in_environ_for_subprocess_inheritance(self, monkeypatch):
        """Ensures password is exported to os.environ for subprocess inheritance."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        test_password = "subprocess_password"
        monkeypatch.setattr("getpass.getpass", lambda prompt: test_password)

        ensure_ad_password()

        # Verify it's in os.environ for subprocess.run to inherit
        assert os.environ[ENV_VAR] == test_password

        # Clean up
        os.environ.pop(ENV_VAR, None)

    def test_prints_hint_on_first_prompt(self, monkeypatch, capsys):
        """Prints hint showing how to export password across shells."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.setattr("getpass.getpass", lambda prompt: "test_password")

        ensure_ad_password()

        captured = capsys.readouterr()
        assert "Cached credential for this process" in captured.err
        assert ENV_VAR in captured.err

        # Clean up
        os.environ.pop(ENV_VAR, None)
