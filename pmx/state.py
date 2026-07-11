"""Read/write for state/guests.jsonl.

Append-only JSON Lines; each record is a dict with:
  hostname, vmid, mac, ip, kind ('vm'|'lxc'), os ('ubuntu'|'rocky'),
  domain_joined (bool), cephfs_mounts (list[str]), rbd_disk (int|None),
  extra_packages (list[str]), static_ip (str|None), static_gw (str|None),
  created_at (ISO8601 str), destroyed_at (ISO8601 str, '' while live).

The log is never rewritten in place. A destroyed guest is recorded by appending
a tombstone — a copy of its last live record with destroyed_at set — so the file
stays an immutable audit trail. find_by_name treats a hostname whose newest
record is a tombstone as absent, so a destroyed guest is no longer "findable" as
a live one, while a name that is destroyed and later re-created reads as live
again (its newest record wins).
"""

# FCIS: functional core

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class GuestRecord:
    hostname: str
    vmid: int
    mac: str
    ip: str
    kind: str
    os: str
    domain_joined: bool
    cephfs_mounts: list[str] = field(default_factory=list)
    rbd_disk: int | None = None
    extra_packages: list[str] = field(default_factory=list)
    static_ip: str | None = None
    static_gw: str | None = None
    created_at: str = ""
    destroyed_at: str = ""

    @property
    def is_tombstone(self) -> bool:
        """True if this record marks the guest as destroyed."""
        return bool(self.destroyed_at)


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def read_all(log_path: str | Path) -> list[GuestRecord]:
    """Return every record in the log, tombstones included; [] if no file."""
    p = _resolve(log_path)
    if not p.exists():
        return []
    records: list[GuestRecord] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        records.append(GuestRecord(**raw))
    return records


def find_by_name(log_path: str | Path, name: str) -> GuestRecord | None:
    """The live record for a hostname, or None.

    Returns the most recent record matching the hostname — unless that record is
    a tombstone, meaning the guest is currently destroyed, in which case the
    guest is treated as absent (None). A name that was destroyed and later
    re-created reads as live again, since its newest record is the re-creation.
    """
    matches = [r for r in read_all(log_path) if r.hostname == name]
    if not matches:
        return None
    latest = matches[-1]
    return None if latest.is_tombstone else latest


def append(log_path: str | Path, record: GuestRecord) -> None:
    """Append a single record. Creates the file and parent dir if needed."""
    p = _resolve(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(record)
    if not payload.get("created_at"):
        payload["created_at"] = datetime.now(tz=timezone.utc).isoformat()
    with p.open("a") as f:
        f.write(json.dumps(payload, sort_keys=True))
        f.write("\n")


def tombstone(log_path: str | Path, name: str) -> GuestRecord | None:
    """Mark a guest destroyed by appending a tombstone of its last live record.

    Returns the tombstone record written, or None if there was no live record to
    tombstone (e.g. a guest pmx never tracked, or one already tombstoned). The
    tombstone copies the live record verbatim with destroyed_at stamped, so the
    guest's final vmid/ip/mac are preserved for audit. Idempotent: once a guest
    is tombstoned, find_by_name reads it as absent and a second call no-ops.
    """
    live = find_by_name(log_path, name)
    if live is None:
        return None
    stone = replace(live, destroyed_at=datetime.now(tz=timezone.utc).isoformat())
    append(log_path, stone)
    return stone
