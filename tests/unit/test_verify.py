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


def _caps_result(mds: str) -> MagicMock:
    import json

    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    r.stdout = json.dumps([{
        "entity": "client.test",
        "key": "REDACTED",
        "caps": {"mds": mds, "mon": "allow r fsname=cephfs", "osd": "allow rw tag cephfs data=cephfs"},
    }])
    return r


def _ok() -> MagicMock:
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    return r


def _fail() -> MagicMock:
    r = MagicMock()
    r.returncode = 1
    r.stderr = "no such mount"
    return r


def _fs_state(kind: str):
    from pmx.state import GuestRecord

    return GuestRecord(
        hostname="test",
        vmid=101,
        mac="aa:bb:cc:dd:ee:ff",
        ip="192.168.9.80",
        kind=kind,
        os="ubuntu",
        domain_joined=True,
        cephfs_mounts=["supernote:/mnt/sn"],
        cephx_entity="client.test",
    )


def test_verify_cephfs_vm_checks_pass() -> None:
    """A VM with a CephFS mount gets a caps check on the node plus one identity
    check per mount on the guest: 3 base + caps + 1 mount = 5 OK."""
    with patch("pmx.verify.load") as mock_load, \
         patch("pmx.verify.find_by_name") as mock_find, \
         patch("pmx.verify.subprocess.run") as mock_run, \
         patch("pmx.verify.click.echo") as mock_echo:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.ad_domain = "broken.wrx"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        mock_load.return_value = cfg
        mock_find.return_value = _fs_state("vm")
        mock_run.side_effect = [
            _caps_result("allow rw fsname=cephfs path=/supernote"),
            _ok(), _ok(), _ok(),  # sssd, id, sudoers
            _ok(),                # mount identity
        ]

        assert run("test") == 0

        ok_calls = [c for c in mock_echo.call_args_list if "[ OK ]" in str(c)]
        assert len(ok_calls) == 5
        # Caps are read on the node; the mount identity is checked on the guest.
        caps_cmd = mock_run.call_args_list[0][0][0]
        assert "root@192.168.9.12" in caps_cmd
        assert "ceph auth get client.test -f json" in caps_cmd[-1]
        mount_cmd = mock_run.call_args_list[-1][0][0]
        assert "ansible@192.168.9.80" in mount_cmd
        assert "/mnt/sn" in mount_cmd[-1]
        assert "name=test" in mount_cmd[-1]


def test_verify_cephfs_wrong_identity_fails() -> None:
    """A mount that is not authenticated as client.<name> fails the run and names the dest."""
    with patch("pmx.verify.load") as mock_load, \
         patch("pmx.verify.find_by_name") as mock_find, \
         patch("pmx.verify.subprocess.run") as mock_run, \
         patch("pmx.verify.click.echo") as mock_echo:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.ad_domain = "broken.wrx"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        mock_load.return_value = cfg
        mock_find.return_value = _fs_state("vm")
        mock_run.side_effect = [
            _caps_result("allow rw fsname=cephfs path=/supernote"),
            _ok(), _ok(), _ok(),
            _fail(),
        ]

        assert run("test") == 1
        fails = [str(c) for c in mock_echo.call_args_list if "[FAIL]" in str(c)]
        assert len(fails) == 1
        assert "/mnt/sn" in fails[0]
        assert "client.test" in fails[0]


def test_verify_cephfs_missing_caps_fails() -> None:
    """Caps that don't cover a requested subpath fail before any guest check runs."""
    with patch("pmx.verify.load") as mock_load, \
         patch("pmx.verify.find_by_name") as mock_find, \
         patch("pmx.verify.subprocess.run") as mock_run, \
         patch("pmx.verify.click.echo") as mock_echo:

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.ad_domain = "broken.wrx"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        mock_load.return_value = cfg
        mock_find.return_value = _fs_state("vm")
        mock_run.side_effect = [_caps_result("allow rw fsname=cephfs path=/other")]

        assert run("test") == 1
        assert mock_run.call_count == 1
        fails = [str(c) for c in mock_echo.call_args_list if "[FAIL]" in str(c)]
        assert len(fails) == 1
        assert "do not cover /supernote" in fails[0]


def test_verify_cephfs_lxc_checks_run_on_node() -> None:
    """For an LXC the identity check targets the host-side passthrough mount on
    the node that hosts the container."""
    with patch("pmx.verify.load") as mock_load, \
         patch("pmx.verify.find_by_name") as mock_find, \
         patch("pmx.verify.query_cluster") as mock_query, \
         patch("pmx.verify.subprocess.run") as mock_run, \
         patch("pmx.verify.click.echo"):

        cfg = MagicMock()
        cfg.state_log_path = "/tmp/state.jsonl"
        cfg.ad_domain = "broken.wrx"
        cfg.proxmox_ssh_host = "root@192.168.9.12"
        mock_load.return_value = cfg
        mock_find.return_value = _fs_state("lxc")
        mock_query.return_value = {"test": (201, "lxc", "kelvin")}
        mock_run.side_effect = [
            _caps_result("allow rw fsname=cephfs path=/supernote"),
            _ok(), _ok(), _ok(),
            _ok(),
        ]

        assert run("test") == 0
        mount_cmd = mock_run.call_args_list[-1][0][0]
        assert "root@192.168.9.12" in mount_cmd
        assert "ssh -o BatchMode=yes kelvin" in mount_cmd[-1]
        assert "/mnt/pmx-passthrough/test/supernote" in mount_cmd[-1]
        assert "name=test" in mount_cmd[-1]


def test_uncovered_subpaths() -> None:
    from pmx.verify import _uncovered_subpaths

    root = "allow rw fsname=cephfs"
    two = "allow rw fsname=cephfs path=/a, allow rw fsname=cephfs path=/b/c"
    assert _uncovered_subpaths(root, ["/anything", "/"]) == []
    assert _uncovered_subpaths(two, ["/a", "/a/deeper", "/b/c"]) == []
    assert _uncovered_subpaths(two, ["/b", "/ab"]) == ["/b", "/ab"]
