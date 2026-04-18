# pmx Provisioning — Phase 7: Destroy, Reconfigure, Verify

**Goal:** Lifecycle commands beyond creation. `pmx destroy <name>` removes the AD computer object via `adcli delete-computer` (unless `--no-domain` was used) then tears down the Proxmox resource. `pmx reconfigure <name>` re-runs the configure phase against an existing guest. `pmx verify <name>` runs a live smoke test (`id Administrator@broken.wrx`, sudo presence, sssd active) and exits non-zero on failure.

**Architecture:**
- `pmx/state.py` provides a read-side API for `state/guests.jsonl` (append-only JSON lines). This phase introduces the reader; Phase 8 wires the write-side via the `post_create_hook` role. For Phase 7 to be testable before Phase 8 lands, the reader is also used by the `pmx verify` command via `--from-state/--by-name` dispatch; when a name isn't in the log, commands fall back to querying Proxmox directly or print a warning.
- `pmx destroy` runs a small inline playbook (`destroy.yml`) that locates the guest by name (`qm list` / `pct list`), runs `adcli delete-computer` inside the guest before shutdown (requires the guest to still be up and reachable), then stops and destroys.
- `pmx reconfigure` replays `provision.yml`'s configure play by re-adding the existing guest to the in-memory inventory and invoking just the configure section via a dedicated `reconfigure.yml` wrapper.
- `pmx verify` is a pure Python subprocess runner — no playbook — because it's read-only and needs crisp exit codes.

**Tech Stack:** `adcli` on the guest, `ssh` from the workstation, small Python argparse dispatch, a slim `reconfigure.yml` wrapper.

**Scope:** Phase 7 of 8.

**Codebase verified:** 2026-04-18. Phase 1–6 artifacts in place. `pmx/state.py` does NOT exist yet (Phase 1 listed it as a stretch for Phase 7). `state/guests.jsonl` does not exist (Phase 8 will start writing it; Phase 7 handles "file missing" as a non-fatal case gracefully).

**External dependency investigation findings:**
- ✓ `adcli delete-computer <computer-name> -U <user> --stdin-password` works against Samba AD 4.x; discovers the domain via DNS SRV. Confirmed current per [adcli(8) man page, 2024-2026](https://manpages.debian.org/unstable/adcli/adcli.8.en.html).
- ✓ `qm destroy <vmid> --purge` removes backup-job references; `--destroy-unreferenced-disks` is destructive and opt-in.
- ✓ `pct destroy <vmid> --purge` handles LXCs equivalently. LXC always deletes the rootfs; there is no `--keep-disk`.
- ✓ `realm leave` as a preferred alternative to `adcli delete-computer`: it works but leaves the computer account in AD as a stale object. `adcli delete-computer` is the clean choice.
- 📖 Sources: [adcli man page](https://manpages.debian.org/unstable/adcli/adcli.8.en.html), [Proxmox forum: difference between destroy & purge](https://forum.proxmox.com/threads/difference-between-destroy-purge-vm.100996/), [realmd leave semantics](https://www.freedesktop.org/software/realmd/docs/).

---

## Acceptance Criteria Coverage

### pmx-provisioning.AC12: pmx destroy
- **pmx-provisioning.AC12.1 Success:** Confirms, runs `adcli delete-computer`, then `qm destroy` or `pct destroy`
- **pmx-provisioning.AC12.2 Success:** `--no-domain` guests skip adcli with a warning and still destroy cleanly
- **pmx-provisioning.AC12.3 Edge:** Guest not in `state/guests.jsonl` destroys with a warning, no failure

### pmx-provisioning.AC13: pmx reconfigure
- **pmx-provisioning.AC13.1 Success:** Re-runs configure phase against an existing guest
- **pmx-provisioning.AC13.2 Success:** Second consecutive reconfigure is a no-op (idempotent)
- **pmx-provisioning.AC13.3 Success:** Reconfigure on a previously-failed configure completes AD join

### pmx-provisioning.AC14: pmx verify smoke test
- **pmx-provisioning.AC14.1 Success:** Healthy domain-joined guest returns exit 0
- **pmx-provisioning.AC14.2 Failure:** Stopped sssd returns non-zero with "sssd not active"
- **pmx-provisioning.AC14.3 Failure:** Cannot resolve `Administrator@broken.wrx` returns non-zero

---

<!-- START_TASK_1 -->
### Task 1: `pmx/state.py` — read/write guest state log

**Verifies:** pmx-provisioning.AC12.3 (graceful missing-state handling)

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/state.py`
- Create: `/home/sysop/proxmox-manage/tests/unit/test_state.py`

**Implementation:**

`pmx/state.py`:
```python
"""Read/write for state/guests.jsonl.

Append-only JSON Lines; each record is a dict with:
  hostname, vmid, mac, ip, kind ('vm'|'lxc'), os ('ubuntu'|'rocky'),
  domain_joined (bool), cephfs_mounts (list[str]), rbd_disk (int|None),
  extra_packages (list[str]), static_ip (str|None), static_gw (str|None),
  created_at (ISO8601 str).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


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


def iter_records(log_path: str | Path) -> Iterator[GuestRecord]:
    yield from read_all(log_path)


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
```

`tests/unit/test_state.py`:
```python
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
```

**Verification:**

```bash
cd /home/sysop/proxmox-manage
uv run pytest tests/unit/test_state.py -v
```
Expected: 3 passed.

**Commit:** `feat(state): add pmx/state.py with read/find/append for guests.jsonl`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: `pmx destroy <name>` — adcli cleanup + pct/qm destroy

**Verifies:** pmx-provisioning.AC12.1, pmx-provisioning.AC12.2, pmx-provisioning.AC12.3

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/destroy.py`
- Create: `/home/sysop/proxmox-manage/ansible/playbooks/destroy.yml`
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` (replace `cmd_destroy` stub)

**Implementation:**

`pmx/destroy.py` — orchestrator that locates the guest, consults the state log, and runs the destroy playbook:
```python
"""pmx destroy — remove AD computer object and destroy Proxmox resource."""

from __future__ import annotations

import subprocess

import click

from pmx.ansible_runner import run_playbook
from pmx.config import load
from pmx.credentials import ensure_ad_password
from pmx.state import find_by_name


def run(name: str, yes: bool) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)

    # Look up vmid + kind via the cluster directly (authoritative).
    cluster = _query_cluster(cfg.proxmox_ssh_host)
    if name not in cluster:
        click.echo(f"No guest named {name!r} found on the cluster.", err=True)
        return 1
    vmid, kind = cluster[name]

    if state is None:
        click.echo(
            f"Warning: {name} is not in {cfg.state_log_path}. "
            f"Proceeding with destroy but skipping AD computer object cleanup.",
            err=True,
        )
        domain_joined = False
    else:
        domain_joined = state.domain_joined

    if not yes:
        click.confirm(
            f"Destroy {kind} {name} (vmid {vmid})"
            f"{' and remove AD computer object' if domain_joined else ''}?",
            abort=True,
        )

    if domain_joined:
        ensure_ad_password()

    extra_vars = {
        "target_node": cfg.default_node,
        "guest_name": name,
        "guest_vmid": vmid,
        "guest_kind": kind,
        "guest_ip": state.ip if state else None,
        "domain_join": domain_joined,
        "ad_domain": cfg.ad_domain,
        "ad_join_user": cfg.ad_join_user,
    }
    return run_playbook("destroy.yml", extra_vars)


def _query_cluster(ssh_host: str) -> dict[str, tuple[int, str]]:
    """Return {name: (vmid, kind)} discovered via ssh qm list + pct list."""
    cmd = ["ssh", "-o", "BatchMode=yes", ssh_host, "qm list; echo ---; pct list"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
    guests: dict[str, tuple[int, str]] = {}
    kind = "vm"
    for line in result.stdout.splitlines():
        if line.strip() == "---":
            kind = "lxc"
            continue
        parts = line.split()
        if not parts or parts[0] in ("VMID", "---"):
            continue
        try:
            vmid = int(parts[0])
        except ValueError:
            continue
        # qm list: VMID NAME ...
        # pct list: VMID STATUS LOCK NAME (older) or VMID STATUS NAME (newer)
        if kind == "vm":
            guests[parts[1]] = (vmid, "vm")
        else:
            guests[parts[-1]] = (vmid, "lxc")
    return guests
```

`ansible/playbooks/destroy.yml`:
```yaml
---
# Destroy sequence:
#   1. (optional) ssh to guest and run `adcli delete-computer`
#   2. stop + destroy the Proxmox resource on the node

- name: Pre-destroy AD cleanup (if domain-joined and reachable)
  hosts: localhost
  gather_facts: false
  become: false
  tasks:
    - name: Run adcli delete-computer on the guest
      ansible.builtin.shell: |
        set -o pipefail
        printf '%s' "$AD_JOIN_PASSWORD" \
        | ssh -o StrictHostKeyChecking=accept-new -o BatchMode=no \
              {{ 'ansible' if guest_kind == 'vm' else 'root' }}@{{ guest_ip }} \
              "sudo adcli delete-computer $(hostname -s) -U {{ ad_join_user }} --stdin-password --domain={{ ad_domain }} || echo 'adcli delete-computer failed (non-fatal)'"
      args:
        executable: /bin/bash
      when: domain_join | bool and guest_ip is not none
      no_log: true
      register: adcli_out
      changed_when: adcli_out.rc == 0
      failed_when: false

- name: Destroy Proxmox resource
  hosts: "{{ target_node }}"
  gather_facts: false
  become: false
  tasks:
    - name: Stop VM
      ansible.builtin.command: "qm stop {{ guest_vmid }}"
      when: guest_kind == 'vm'
      failed_when: false
      changed_when: true

    - name: Destroy VM
      ansible.builtin.command: "qm destroy {{ guest_vmid }} --purge"
      when: guest_kind == 'vm'
      changed_when: true

    - name: Stop LXC
      ansible.builtin.command: "pct stop {{ guest_vmid }}"
      when: guest_kind == 'lxc'
      failed_when: false
      changed_when: true

    - name: Destroy LXC
      ansible.builtin.command: "pct destroy {{ guest_vmid }} --purge"
      when: guest_kind == 'lxc'
      changed_when: true
```

Modify `pmx/cli.py:cmd_destroy` — replace body:
```python
@main.command("destroy")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip interactive confirmation.")
def cmd_destroy(name: str, yes: bool) -> None:
    """Destroy a guest (removes AD computer object and Proxmox resource)."""
    from pmx import destroy
    sys.exit(destroy.run(name, yes))
```

**Implementation notes:**

- The adcli delete-computer step uses `failed_when: false` plus an embedded `|| echo ...` so a failure (e.g., guest SSH unreachable) is non-fatal. Destroy continues; we accept a stale computer object over a blocked teardown. The operator can always run `adcli delete-computer <name>` manually from the Zentyal box.
- `hostname -s` inside the ssh command resolves the guest's short hostname at teardown time (more reliable than passing `name` from the workstation, which might diverge from `/etc/hostname` after cloud-init).

**Testing:**

Integration test in Task 5.

**Verification:**

Syntax check:
```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/destroy.yml \
  -e target_node=pve01 -e guest_name=x -e guest_vmid=999 -e guest_kind=vm \
  -e guest_ip=192.168.9.80 -e domain_join=true \
  -e ad_domain=broken.wrx -e ad_join_user=jtd
```
Expected: syntax OK.

**Commit:** `feat(destroy): pmx destroy with adcli delete-computer then qm/pct destroy`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: `pmx reconfigure <name>` — re-run configure phase

**Verifies:** pmx-provisioning.AC13.1, pmx-provisioning.AC13.2, pmx-provisioning.AC13.3

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/reconfigure.py`
- Create: `/home/sysop/proxmox-manage/ansible/playbooks/reconfigure.yml`
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` (replace `cmd_reconfigure` stub)

**Implementation:**

`pmx/reconfigure.py`:
```python
"""pmx reconfigure — re-run the configure phase against an existing guest."""

from __future__ import annotations

import click

from pmx.ansible_runner import run_playbook
from pmx.config import load
from pmx.credentials import ensure_ad_password
from pmx.state import find_by_name


def run(name: str) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)
    if state is None:
        click.echo(
            f"No record of {name} in {cfg.state_log_path}. "
            f"pmx reconfigure needs the original build parameters from the state log.",
            err=True,
        )
        return 1

    if state.domain_joined:
        ensure_ad_password()

    extra_vars = {
        "target_node": cfg.default_node,
        "guest_name": state.hostname,
        "guest_vmid": state.vmid,
        "guest_kind": state.kind,
        "guest_os": state.os,
        "guest_ip": state.ip,
        "guest_mac": state.mac,
        "domain_join": state.domain_joined,
        "cephfs_mounts": state.cephfs_mounts,
        "rbd_disk": state.rbd_disk,
        "extra_packages": state.extra_packages,
        "static_ip": state.static_ip,
        "static_gw": state.static_gw,
        "ad_domain": cfg.ad_domain,
        "ad_realm": cfg.ad_realm,
        "ad_join_user": cfg.ad_join_user,
        "default_storage": cfg.default_storage,
        "default_lxc_storage": cfg.default_lxc_storage,
        "default_bridge": cfg.default_bridge,
        "proxmox_api_host": cfg.proxmox_api_host,
    }
    return run_playbook("reconfigure.yml", extra_vars)
```

This task extracts the configure play into a shared `_configure.yml`, then wires it into both `provision.yml` and the new `reconfigure.yml`. Three ordered steps.

**Step A: Extract `_configure.yml`**

Create `/home/sysop/proxmox-manage/ansible/playbooks/_configure.yml` with the full configure-play content. This must match exactly what Phase 6 Task 5 had already put in the "Configure guest" play of `provision.yml` — same tasks, same conditions, same order. (The underscore prefix is a convention for "internal, not invoked directly".)

```yaml
---
- name: Configure guest
  hosts: just_created
  gather_facts: true
  become: "{{ guest_kind == 'vm' }}"
  tasks:
    - name: Run common bootstrap
      ansible.builtin.include_role:
        name: common

    - name: Join guest to AD (Ubuntu)
      ansible.builtin.include_role:
        name: ad_join_ubuntu
      when: domain_join | bool and guest_os == 'ubuntu'

    - name: Join guest to AD (Rocky)
      ansible.builtin.include_role:
        name: ad_join_rocky
      when: domain_join | bool and guest_os == 'rocky'

    - name: Attach extra RBD disk (VM only)
      ansible.builtin.include_role:
        name: attach_rbd_disk
      when: rbd_disk is not none

    - name: Mount CephFS shares
      ansible.builtin.include_role:
        name: mount_cephfs
      when: cephfs_mounts | default([]) | length > 0

    - name: Install extra packages
      ansible.builtin.include_role:
        name: extra_packages
      when: extra_packages | default([]) | length > 0
```

**Step B: Modify `provision.yml`**

Replace the entire existing "Configure guest" play (the second play) with a single `import_playbook` line. After the edit, `provision.yml` has exactly two entries: the "Create guest on Proxmox" play (unchanged) and a bottom-of-file `import_playbook: _configure.yml`:

```yaml
- name: Configure guest
  ansible.builtin.import_playbook: _configure.yml
```

**Step C: Create `reconfigure.yml`**

`reconfigure.yml` is a two-step playbook: (1) a localhost play that `add_host`s the known-existing guest into `just_created` using vars from the state log, (2) an `import_playbook: _configure.yml` to run exactly the configure steps:

```yaml
---
# Reconfigure an existing guest. The first play re-hydrates the dynamic
# inventory from state/guests.jsonl via the CLI-supplied extra-vars; the
# second play reuses the shared configure playbook.

- name: Register existing guest in dynamic inventory
  hosts: localhost
  gather_facts: false
  become: false
  tasks:
    - name: add_host for existing guest
      ansible.builtin.add_host:
        name: "{{ guest_name }}"
        ansible_host: "{{ guest_ip }}"
        ansible_user: "{{ 'ansible' if guest_kind == 'vm' else 'root' }}"
        ansible_ssh_common_args: "-o StrictHostKeyChecking=accept-new"
        groups: just_created
        guest_vmid: "{{ guest_vmid }}"
        guest_kind: "{{ guest_kind }}"
        guest_os: "{{ guest_os }}"
        guest_mac: "{{ guest_mac }}"
        domain_join: "{{ domain_join }}"
        ad_domain: "{{ ad_domain }}"
        ad_realm: "{{ ad_realm }}"
        ad_join_user: "{{ ad_join_user }}"
        cephfs_mounts: "{{ cephfs_mounts }}"
        rbd_disk: "{{ rbd_disk }}"
        extra_packages: "{{ extra_packages }}"
        static_ip: "{{ static_ip }}"
        static_gw: "{{ static_gw }}"

- name: Configure guest
  ansible.builtin.import_playbook: _configure.yml
```

**Step D: Wire the CLI**

Modify `pmx/cli.py:cmd_reconfigure` body:
```python
@main.command("reconfigure")
@click.argument("name")
def cmd_reconfigure(name: str) -> None:
    """Re-run the configure phase against an existing guest."""
    from pmx import reconfigure
    sys.exit(reconfigure.run(name))
```

**Implementation notes:**

- `import_playbook` is evaluated at parse time and each imported play runs against its own `hosts:` target. For `provision.yml` this means the create play runs against `{{ target_node }}`, the imported configure play runs against `just_created`. No cross-contamination.
- The underscore-prefix on `_configure.yml` is documentation only — Ansible doesn't treat it specially, but the convention prevents operators from running it directly via `ansible-playbook _configure.yml` (which would fail because `just_created` is empty without a prior `add_host`).

**Testing:**

Integration test in Task 5.

**Verification:**

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/reconfigure.yml \
  -e target_node=pve01 -e guest_name=x -e guest_vmid=999 -e guest_kind=vm \
  -e guest_os=ubuntu -e guest_ip=192.168.9.80 -e guest_mac=aa:bb:cc:dd:ee:ff \
  -e domain_join=false -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e static_gw=null \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e proxmox_api_host=192.168.9.12
```
Expected: syntax OK for both `reconfigure.yml` and `provision.yml`.

**Commit:** `feat(reconfigure): pmx reconfigure replays configure play via shared _configure.yml`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: `pmx verify <name>` — SSH-based smoke test

**Verifies:** pmx-provisioning.AC14.1, pmx-provisioning.AC14.2, pmx-provisioning.AC14.3

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/verify.py`
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` (replace `cmd_verify` stub)

**Implementation:**

`pmx/verify.py`:
```python
"""pmx verify — live smoke test against a domain-joined guest."""

from __future__ import annotations

import subprocess

import click

from pmx.config import load
from pmx.state import find_by_name


def run(name: str) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)
    if state is None:
        click.echo(f"No record of {name} in {cfg.state_log_path}.", err=True)
        return 2

    ssh_user = "ansible" if state.kind == "vm" else "root"
    host = f"{ssh_user}@{state.ip}"

    # Check ordering: sssd active, then id lookup. Keeps failure messages specific.
    checks = [
        ("sssd is active", "systemctl is-active sssd", "sssd not active (AC14.2)"),
        (
            "id Administrator@broken.wrx",
            f"id Administrator@{cfg.ad_domain}",
            "Cannot resolve Administrator@" + cfg.ad_domain + " (AC14.3)",
        ),
        (
            "sudoers drop-in validates",
            "test -f /etc/sudoers.d/domain-admins && /usr/sbin/visudo -cf /etc/sudoers.d/domain-admins",
            "sudoers drop-in missing or invalid",
        ),
    ]

    for label, remote_cmd, err_msg in checks:
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            host,
            remote_cmd,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            click.echo(f"[FAIL] {label}: {err_msg}", err=True)
            click.echo(result.stderr, err=True)
            return 1
        click.echo(f"[ OK ] {label}")

    click.echo(f"{name}: healthy.")
    return 0
```

Modify `pmx/cli.py:cmd_verify`:
```python
@main.command("verify")
@click.argument("name")
def cmd_verify(name: str) -> None:
    """Run smoke tests against a domain-joined guest."""
    from pmx import verify
    sys.exit(verify.run(name))
```

**Testing:**

Unit test the check sequencing — `tests/unit/test_verify.py` — Verifies `pmx-provisioning.AC14.2`:
- Mock `subprocess.run` to simulate `systemctl is-active sssd` returning non-zero; assert `run()` returns 1 and error message contains "sssd not active (AC14.2)".
- Simulate all three checks succeeding; assert `run()` returns 0.
- Simulate state lookup returning None; assert `run()` returns 2.

**Verification:**

```bash
cd /home/sysop/proxmox-manage
uv run pytest tests/unit/test_verify.py -v
```
Expected: tests pass.

Live verification is covered by Task 5 integration test.

**Commit:** `feat(verify): pmx verify runs sssd/id/sudoers smoke tests via ssh`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: End-to-end lifecycle integration test

**Verifies:** pmx-provisioning.AC12.1, AC12.2, AC12.3, AC13.1, AC13.2, AC14.1

**Files:**
- Create: `/home/sysop/proxmox-manage/tests/integration/test_lifecycle.sh`

**Implementation:**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD first.}"

NAME="pmxtest-lifecycle-$$"

echo "=== Create ${NAME} (Ubuntu VM, domain-joined) ==="
uv run pmx new --name "${NAME}" --kind vm --os ubuntu \
  --cores 2 --memory 2048 --disk 16

echo "=== Verify — expect exit 0 (AC14.1) ==="
uv run pmx verify "${NAME}"

echo "=== Reconfigure — first run, should be no-op but exit 0 (AC13.1, AC13.2) ==="
uv run pmx reconfigure "${NAME}"

echo "=== Reconfigure again — still a no-op ==="
uv run pmx reconfigure "${NAME}"

echo "=== Destroy — confirm via --yes (AC12.1) ==="
uv run pmx destroy "${NAME}" --yes

echo "=== Post-destroy: verify vmid is gone ==="
vmid_probe=$(ssh root@192.168.9.12 "qm list | awk -v n=${NAME} '\$2==n{print \$1}'")
if [ -n "${vmid_probe}" ]; then
  echo "BUG: ${NAME} still in qm list after destroy"
  exit 1
fi

echo "=== AC12.2 — build with --no-domain, verify destroy skips adcli ==="
NONAD="pmxtest-nodomain-$$"
uv run pmx new --name "${NONAD}" --kind lxc --os ubuntu --no-domain \
  --cores 1 --memory 512 --disk 8
uv run pmx destroy "${NONAD}" --yes 2>&1 | tee /tmp/destroy.log
grep -q "skipping AD computer object cleanup" /tmp/destroy.log

echo "=== AC12.3 — destroy a guest not in state log ==="
# Create a guest by hand via pct using the Rocky LXC template that `pmx seed`
# guarantees is present (Ubuntu LXC templates are NOT fetched by seed, so we
# can't assume they exist here). Then destroy via pmx; expect warning + clean destroy.
ORPHAN="pmxtest-orphan-$$"
ssh root@192.168.9.12 "pct create \$(pvesh get /cluster/nextid) \
  cephfs:vztmpl/\$(pveam list cephfs | grep -oE 'rockylinux-9-default_[^ ]+' | head -1) \
  --hostname ${ORPHAN} --memory 256 --rootfs cephfs:1 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1"
uv run pmx destroy "${ORPHAN}" --yes 2>&1 | tee /tmp/destroy2.log
grep -q "not in" /tmp/destroy2.log

echo "All lifecycle tests passed."
```

**Verification:**

```bash
chmod +x tests/integration/test_lifecycle.sh
./tests/integration/test_lifecycle.sh
```
Expected: all blocks pass, final message "All lifecycle tests passed."

**Commit:** `test(lifecycle): end-to-end create/verify/reconfigure/destroy harness`
<!-- END_TASK_5 -->

---

## Phase 7 done when

- `pmx verify <name>` returns 0 for a healthy domain-joined guest (AC14.1); returns non-zero with "sssd not active" when SSSD is stopped (AC14.2); returns non-zero on unresolvable Administrator@broken.wrx (AC14.3)
- `pmx reconfigure <name>` re-runs the configure play and the second consecutive call reports zero changes (AC13.1, AC13.2)
- `pmx reconfigure <name>` run against a guest whose previous configure failed completes the AD join on the next try (AC13.3)
- `pmx destroy <name> --yes` runs `adcli delete-computer` from inside the guest then tears down the Proxmox resource (AC12.1)
- `pmx destroy <name> --yes` on a `--no-domain` guest skips the adcli step with a warning and still destroys (AC12.2)
- `pmx destroy <name> --yes` on a guest not in `state/guests.jsonl` warns and still destroys cleanly (AC12.3)
- `tests/unit/test_state.py` passes
- `tests/unit/test_verify.py` passes
- `tests/integration/test_lifecycle.sh` passes against the real cluster
- Clean `git status` after commits from Tasks 1–5
