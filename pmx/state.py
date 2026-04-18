"""Read/write for state/guests.jsonl.

Append-only JSON Lines; each record is a dict with:
  hostname, vmid, mac, ip, kind ('vm'|'lxc'), os ('ubuntu'|'rocky'),
  domain_joined (bool), cephfs_mounts (list[str]), rbd_disk (int|None),
  extra_packages (list[str]), static_ip (str|None), static_gw (str|None),
  created_at (ISO8601 str).
"""

# FCIS: functional core

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
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


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def read_all(log_path: str | Path) -> list[GuestRecord]:
    """Return every record in the log; returns [] if the file doesn't exist."""
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
    """Most recent record matching hostname; None if missing."""
    matches = [r for r in read_all(log_path) if r.hostname == name]
    return matches[-1] if matches else None


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
