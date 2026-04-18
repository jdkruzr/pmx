"""Tests for pmx/verify.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pmx.verify import run


def test_verify_state_lookup_none_returns_2() -> None:
    """Test that verify returns 2 when state lookup returns None."""
    with patch("pmx.verify.load") as mock_load, \
         patch("pmx.verify.find_by_name") as mock_find:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.ad_domain = "broken.wrx"
        mock_load.return_value = cfg
        mock_find.return_value = None

        result = run("nonexistent")

        assert result == 2


def test_verify_sssd_not_active_returns_1_with_ac14_2_message() -> None:
    """Test that sssd check failure returns 1 with AC14.2 message."""
    from pmx.state import GuestRecord

    with patch("pmx.verify.load") as mock_load, \
         patch("pmx.verify.find_by_name") as mock_find, \
         patch("pmx.verify.subprocess.run") as mock_run, \
         patch("pmx.verify.click.echo") as mock_echo:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.ad_domain = "broken.wrx"
        mock_load.return_value = cfg

        # Mock state with VM kind (uses ansible user)
        state = GuestRecord(
            hostname="test",
            vmid=101,
            mac="aa:bb:cc:dd:ee:ff",
            ip="192.168.9.80",
            kind="vm",
            os="ubuntu",
            domain_joined=True,
        )
        mock_find.return_value = state

        # First call (sssd check) returns non-zero
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "sssd not running"
        mock_run.return_value = mock_result

        result = run("test")

        assert result == 1
        # Verify error message contains AC14.2
        error_calls = [call for call in mock_echo.call_args_list
                      if "AC14.2" in str(call)]
        assert len(error_calls) > 0


def test_verify_all_checks_succeed_returns_0() -> None:
    """Test that all checks passing returns 0."""
    from pmx.state import GuestRecord

    with patch("pmx.verify.load") as mock_load, \
         patch("pmx.verify.find_by_name") as mock_find, \
         patch("pmx.verify.subprocess.run") as mock_run, \
         patch("pmx.verify.click.echo") as mock_echo:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.ad_domain = "broken.wrx"
        mock_load.return_value = cfg

        # Mock state with LXC kind (uses root user)
        state = GuestRecord(
            hostname="test",
            vmid=201,
            mac="aa:bb:cc:dd:ee:ff",
            ip="192.168.9.81",
            kind="lxc",
            os="ubuntu",
            domain_joined=True,
        )
        mock_find.return_value = state

        # All calls return success
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run("test")

        assert result == 0
        # Verify that [ OK ] messages were printed
        ok_calls = [call for call in mock_echo.call_args_list
                   if "[ OK ]" in str(call)]
        assert len(ok_calls) == 3  # Three checks
