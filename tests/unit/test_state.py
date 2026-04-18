"""Tests for pmx/state.py."""

from __future__ import annotations

import json
from pathlib import Path

from pmx.state import GuestRecord, append, find_by_name, read_all


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
