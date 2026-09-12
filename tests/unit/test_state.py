"""Tests for pmx/state.py."""

from __future__ import annotations

import json
from pathlib import Path

from pmx.state import GuestRecord, append, find_by_name, read_all, tombstone


def _rec(name: str, vmid: int, **kw) -> GuestRecord:
    base = dict(
        hostname=name,
        vmid=vmid,
        mac="aa:bb:cc:dd:ee:ff",
        ip="192.168.9.80",
        kind="vm",
        os="ubuntu",
        domain_joined=True,
    )
    base.update(kw)
    return GuestRecord(**base)


def test_read_all_missing_file(tmp_path: Path) -> None:
    assert read_all(tmp_path / "nope.jsonl") == []


def test_append_creates_file_and_parent(tmp_path: Path) -> None:
    log = tmp_path / "state" / "guests.jsonl"
    rec = GuestRecord(
        hostname="foo",
        vmid=101,
        mac="aa:bb:cc:dd:ee:ff",
        ip="192.168.9.80",
        kind="vm",
        os="ubuntu",
        domain_joined=True,
    )
    append(log, rec)
    assert log.exists()
    data = [json.loads(line) for line in log.read_text().splitlines()]
    assert data[0]["hostname"] == "foo"
    assert data[0]["vmid"] == 101
    assert data[0]["created_at"]  # auto-populated
    assert data[0]["destroyed_at"] == ""  # live by default


def test_find_by_name_returns_most_recent(tmp_path: Path) -> None:
    log = tmp_path / "guests.jsonl"
    append(log, GuestRecord(
        hostname="foo", vmid=101, mac="a", ip="1.1.1.1",
        kind="vm", os="ubuntu", domain_joined=False,
    ))
    append(log, GuestRecord(
        hostname="foo", vmid=102, mac="b", ip="2.2.2.2",
        kind="vm", os="ubuntu", domain_joined=True,
    ))
    assert find_by_name(log, "foo").vmid == 102
    assert find_by_name(log, "missing") is None


def test_tombstone_marks_guest_absent(tmp_path: Path) -> None:
    """After tombstoning, find_by_name reads the guest as absent, but the log
    keeps both records and the tombstone preserves the guest's final identity."""
    log = tmp_path / "guests.jsonl"
    append(log, _rec("foo", 101, ip="192.168.9.81", mac="bc:24:11:aa:bb:cc"))

    stone = tombstone(log, "foo")

    assert stone is not None
    assert stone.is_tombstone
    assert stone.destroyed_at  # stamped
    assert stone.vmid == 101  # identity preserved for audit
    assert stone.ip == "192.168.9.81"
    assert stone.mac == "bc:24:11:aa:bb:cc"

    # Live lookup now reports absent, but the full history is retained.
    assert find_by_name(log, "foo") is None
    assert len(read_all(log)) == 2
    assert read_all(log)[-1].is_tombstone


def test_tombstone_no_live_record_is_noop(tmp_path: Path) -> None:
    """Tombstoning a guest that was never tracked returns None and writes
    nothing — a manually-made guest has no live record to tombstone."""
    log = tmp_path / "guests.jsonl"
    assert tombstone(log, "never-existed") is None
    assert read_all(log) == []


def test_tombstone_is_idempotent(tmp_path: Path) -> None:
    """A second tombstone no-ops: once the newest record is a tombstone, there is
    no live record to copy, so nothing more is appended."""
    log = tmp_path / "guests.jsonl"
    append(log, _rec("foo", 101))

    assert tombstone(log, "foo") is not None
    assert tombstone(log, "foo") is None  # already dead
    assert len(read_all(log)) == 2  # live + one tombstone, no more


def test_recreate_after_tombstone_reads_live(tmp_path: Path) -> None:
    """A name destroyed and later re-created reads as live again: its newest
    record is the re-creation, not the tombstone."""
    log = tmp_path / "guests.jsonl"
    append(log, _rec("foo", 101))
    tombstone(log, "foo")
    append(log, _rec("foo", 202, ip="192.168.9.99"))

    live = find_by_name(log, "foo")
    assert live is not None
    assert live.vmid == 202
    assert live.ip == "192.168.9.99"
    assert not live.is_tombstone


def test_state_log_roundtrip_with_fixture() -> None:
    """Verify state log can be read and types are preserved."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_guests.jsonl"
    records = read_all(fixture_path)
    assert len(records) == 1

    rec = records[0]
    assert isinstance(rec.vmid, int)
    assert rec.vmid == 100
    assert isinstance(rec.domain_joined, bool)
    assert rec.domain_joined is True
    assert isinstance(rec.cephfs_mounts, list)
    assert rec.cephfs_mounts == []
    assert isinstance(rec.extra_packages, list)
    assert rec.extra_packages == []
    assert isinstance(rec.rbd_disk, type(None))
    assert isinstance(rec.created_at, str)
    assert "2026-04-18" in rec.created_at
    assert rec.hostname == "test-ubuntu-vm"
    assert rec.kind == "vm"
    assert rec.os == "ubuntu"
    # A record with no destroyed_at (fixture predates the field) reads as live.
    assert rec.destroyed_at == ""
    assert rec.is_tombstone is False
    # Likewise cephx_entity: the fixture predates it and must still load.
    assert rec.cephx_entity == ""


def test_cephx_entity_roundtrip(tmp_path: Path) -> None:
    """cephx_entity is persisted and read back; it defaults to '' for guests
    without CephFS mounts."""
    log = tmp_path / "guests.jsonl"
    append(log, _rec("fsguest", 101, cephfs_mounts=["supernote:/mnt/sn"],
                     cephx_entity="client.fsguest"))
    append(log, _rec("plain", 102))

    assert find_by_name(log, "fsguest").cephx_entity == "client.fsguest"
    assert find_by_name(log, "plain").cephx_entity == ""
    raw = [json.loads(line) for line in log.read_text().splitlines()]
    assert raw[0]["cephx_entity"] == "client.fsguest"
