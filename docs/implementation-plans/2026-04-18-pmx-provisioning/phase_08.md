# pmx Provisioning — Phase 8: Post-Create Hook and State Log (DHCP Seam)

**Goal:** Every successful build ends by writing a JSON-lines record to `state/guests.jsonl` on the workstation. The write goes through a dedicated `post_create_hook` Ansible role that is **intentionally minimal today** — it logs state and does nothing else. The role is the seam for future Zentyal DHCP reservation wiring, DNS record creation, monitoring registration, etc.

**Architecture:** A tiny role, `post_create_hook`, runs as the final task of the configure play in `_configure.yml`. It accepts the full guest variable set (already on the `just_created` host), renders a JSON line, and appends it via `delegate_to: localhost` so the write lands on the workstation filesystem. The state log path comes from the extra-vars the CLI already passes through (from `pmx/config.py`). The role is parameterless from the operator's perspective — it uses the same variables every other configure-phase role already has.

**Tech Stack:** Ansible `lineinfile` (or `copy`/`to_nice_json` for atomic rewrites), `delegate_to: localhost`.

**Scope:** Phase 8 of 8 (final).

**Codebase verified:** 2026-04-18. Phase 1–7 artifacts in place. `pmx/state.py` has the read-side API and is used by `pmx destroy`/`reconfigure`/`verify`. The configure play in `ansible/playbooks/_configure.yml` currently ends with `extra_packages`; this phase appends a post-hook role include.

**External dependency investigation findings:**
- ✓ N/A — this is internal plumbing only. No new external dependencies.

---

## Acceptance Criteria Coverage

### pmx-provisioning.AC15: State log (DHCP seam)
- **pmx-provisioning.AC15.1 Success:** Every successful build appends one JSON line to `state/guests.jsonl` with `{hostname, vmid, mac, ip, kind, os, domain_joined}` (plus the full build-parameter fields needed by reconfigure: `cephfs_mounts`, `rbd_disk`, `extra_packages`, `static_ip`, `static_gw`, `created_at`)
- **pmx-provisioning.AC15.2 Success:** Log is append-only; old entries preserved
- **pmx-provisioning.AC15.3 Edge:** Missing log file is created on first build

### pmx-provisioning.AC16: Post-create hook contract
- **pmx-provisioning.AC16.1 Success:** `post_create_hook` role receives `{hostname, vmid, mac, ip, kind, os, domain_joined}` variables (plus the rest of the build-parameter set)
- **pmx-provisioning.AC16.2 Success:** Default implementation writes state log only (no other side effects)
- **pmx-provisioning.AC16.3 Documentation:** `docs/extending-post-create.md` describes how to plug in DHCP/DNS integrations

---

<!-- START_TASK_1 -->
### Task 1: `roles/post_create_hook` — write JSONL record to workstation

**Verifies:** pmx-provisioning.AC15.1, pmx-provisioning.AC15.2, pmx-provisioning.AC15.3, pmx-provisioning.AC16.1, pmx-provisioning.AC16.2

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/post_create_hook/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/post_create_hook/defaults/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
# Absolute path on the workstation. The CLI resolves this from
# ~/.config/pmx/config.yml:state_log_path (default: "state/guests.jsonl"
# relative to the repo root) and passes it as an extra-var.
state_log_path: "{{ playbook_dir | dirname }}/state/guests.jsonl"
```

`tasks/main.yml`:
```yaml
---
- name: Build post-hook payload
  ansible.builtin.set_fact:
    pmx_state_record:
      hostname: "{{ guest_name }}"
      vmid: "{{ guest_vmid | int }}"
      mac: "{{ guest_mac | default('') }}"
      ip: "{{ ansible_host }}"
      kind: "{{ guest_kind }}"
      os: "{{ guest_os }}"
      domain_joined: "{{ domain_join | bool }}"
      cephfs_mounts: "{{ cephfs_mounts | default([]) }}"
      rbd_disk: "{{ rbd_disk | default(None) }}"
      extra_packages: "{{ extra_packages | default([]) }}"
      static_ip: "{{ static_ip | default(None) }}"
      static_gw: "{{ static_gw | default(None) }}"
      created_at: "{{ ansible_date_time.iso8601 }}"

- name: Ensure state/ directory exists on workstation
  ansible.builtin.file:
    path: "{{ state_log_path | dirname }}"
    state: directory
    mode: "0755"
  delegate_to: localhost
  become: false

- name: Append record to state log (one JSON line per successful build)
  ansible.builtin.lineinfile:
    path: "{{ state_log_path }}"
    line: "{{ pmx_state_record | to_json(sort_keys=True) }}"
    create: true
    mode: "0644"
    # Always-append behavior: use a unique regexp that matches this run only.
    # The created_at timestamp makes each line unique, so lineinfile never
    # "updates" an existing line and always appends new ones.
    insertafter: EOF
    state: present
  delegate_to: localhost
  become: false

# Future extensions plug in below. Example (commented):
# - name: Register DHCP reservation with Zentyal
#   ansible.builtin.include_tasks: zentyal_dhcp.yml
#   delegate_to: localhost
#   become: false
#   when: dhcp_reservations_enabled | default(false)
```

**Implementation notes:**

- The role runs on `just_created` (the guest is the Ansible host), but each task `delegate_to: localhost` so file writes land on the workstation. Ansible's `ansible_date_time` is available from gathered facts on the guest and used as the record's `created_at`.
- We use `lineinfile` rather than `copy` + template + read-all-records to keep the role append-only and to minimize disk churn. Since each record includes a unique timestamp, `lineinfile` never updates an existing line.
- `to_json(sort_keys=True)` ensures stable field order across runs, matching the `pmx/state.py` reader's tolerance for any JSON field order but making log diffs human-readable.

**Testing:**

Task 3 end-to-end test.

**Verification:**

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=vm -e guest_os=ubuntu -e guest_name=x \
  -e cores=2 -e memory=2048 -e disk=32 -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e static_gw=null -e domain_join=false \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12 -e state_log_path=/tmp/test.jsonl
```
Expected: syntax OK.

**Commit:** `feat(post_create_hook): append JSONL state record to workstation on every successful build`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Wire `post_create_hook` into `_configure.yml`; thread `state_log_path` through the CLI

**Verifies:** pmx-provisioning.AC15.1, pmx-provisioning.AC15.2

**Files:**
- Modify: `/home/sysop/proxmox-manage/ansible/playbooks/_configure.yml`
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` (pass `state_log_path` in the extra-vars dict)

**Implementation:**

Append to `_configure.yml`:
```yaml
    - name: Post-create state log + future extensions
      ansible.builtin.include_role:
        name: post_create_hook
```

Modify `pmx/cli.py:cmd_new` — in the `extra_vars` merge dict, add `state_log_path`:
```python
    extra_vars = _extra_vars_from(kwargs) | {
        "target_node": cfg.default_node,
        "default_storage": cfg.default_storage,
        "default_lxc_storage": cfg.default_lxc_storage,
        "default_bridge": cfg.default_bridge,
        "ad_domain": cfg.ad_domain,
        "ad_realm": cfg.ad_realm,
        "ad_join_user": cfg.ad_join_user,
        "proxmox_api_host": cfg.proxmox_api_host,
        "state_log_path": str(Path(__file__).resolve().parent.parent / cfg.state_log_path),
    }
```

Import `Path` at top of `pmx/cli.py`:
```python
from pathlib import Path
```

**Implementation notes:**

- Resolving `cfg.state_log_path` against the repo root gives absolute paths so ansible's `delegate_to: localhost` writes to the right place regardless of the operator's cwd.
- Reconfigure uses the already-persisted record — it does NOT append a new record, because the guest's build parameters haven't changed. If reconfigure ever adds the ability to mutate parameters (out of scope for Phase 8), we'd revisit.

**Verification:**

Syntax check with `state_log_path` in extra-vars (same as Task 1 Verification).

**Commit:** `feat(cli): pass state_log_path through to Ansible; wire post_create_hook into configure play`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Hook contract doc + end-to-end state log verification

**Verifies:** pmx-provisioning.AC15.1, pmx-provisioning.AC15.2, pmx-provisioning.AC15.3, pmx-provisioning.AC16.3

**Files:**
- Create: `/home/sysop/proxmox-manage/docs/extending-post-create.md`
- Create: `/home/sysop/proxmox-manage/tests/integration/test_state_log.sh`

**Implementation:**

`docs/extending-post-create.md`:

```markdown
# Extending the post-create hook

`ansible/roles/post_create_hook` runs as the final task of the configure play
and is the designated extension point for anything that should fire after a
guest is successfully built: DHCP reservations, DNS records, monitoring
registration, chat-ops notifications, etc.

## Variables available to the role

The guest is the Ansible host during this role, so `ansible_host`,
`ansible_facts`, etc. are all available. Additionally the following extra-vars
are set:

| Variable              | Type             | Notes                                             |
| --------------------- | ---------------- | ------------------------------------------------- |
| `guest_name`          | str              | Hostname / pmx primary key                        |
| `guest_vmid`          | int              | Proxmox VMID                                      |
| `guest_mac`           | str              | Primary NIC MAC                                   |
| `guest_kind`          | "vm" \| "lxc"   | Creation path taken                               |
| `guest_os`            | "ubuntu" \| "rocky" | OS family                                     |
| `domain_join`         | bool             | Whether AD join was performed                     |
| `cephfs_mounts`       | list[str]        | Raw `--cephfs` specs                              |
| `rbd_disk`            | int \| null      | Extra RBD disk size in GiB                        |
| `extra_packages`      | list[str]        | Operator-supplied packages                        |
| `static_ip`           | str \| null      | Static IP CIDR, or null for DHCP                  |
| `static_gw`           | str \| null      | Explicit gateway, or null for inferred .1         |
| `ad_domain`           | str              | e.g. "broken.wrx"                                 |
| `ad_realm`            | str              | e.g. "BROKEN.WRX"                                 |
| `state_log_path`      | str              | Absolute path to `state/guests.jsonl`             |

## Adding a new extension

Create a task file next to `tasks/main.yml` (e.g. `tasks/dhcp_zentyal.yml`) and
include it conditionally:

```yaml
- name: Register DHCP reservation with Zentyal
  ansible.builtin.include_tasks: dhcp_zentyal.yml
  delegate_to: localhost
  become: false
  when: dhcp_reservations_enabled | default(false)
```

Add a defaults entry so the feature is off-by-default:

```yaml
# defaults/main.yml
dhcp_reservations_enabled: false
```

Flip it on in `~/.config/pmx/config.yml` (needs a new loader field) or pass
`-e dhcp_reservations_enabled=true`.

## Contract guarantees

The role always runs last in the configure play. It must NEVER mutate guest
state; it only makes calls to external systems (Zentyal, DNS, monitoring) and
writes to the workstation's state log. If a new extension mutates the guest,
it belongs in a different role, not here.

## State log format

`state/guests.jsonl` is append-only JSON Lines. Each line is one dict with
the fields listed above plus `created_at` (ISO8601 UTC). Reader API lives in
`pmx/state.py`.
```

`tests/integration/test_state_log.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD first.}"

LOG="${REPO_ROOT}/state/guests.jsonl"

# AC15.3 — log missing, first build creates it
rm -f "${LOG}"

NAME1="pmxtest-state1-$$"
uv run pmx new --name "${NAME1}" --kind lxc --os ubuntu --no-domain \
  --cores 1 --memory 512 --disk 8

test -f "${LOG}"
line_count=$(wc -l < "${LOG}")
test "${line_count}" -eq 1

# AC15.1 — record has all expected fields
python3 - <<PY
import json, sys
rec = json.loads(open("${LOG}").readline())
expected = {"hostname","vmid","mac","ip","kind","os","domain_joined",
            "cephfs_mounts","rbd_disk","extra_packages","static_ip",
            "static_gw","created_at"}
missing = expected - set(rec.keys())
assert not missing, f"missing fields: {missing}"
assert rec["hostname"] == "${NAME1}", rec
assert rec["kind"] == "lxc", rec
assert rec["os"] == "ubuntu", rec
assert rec["domain_joined"] is False, rec
PY

# AC15.2 — second build appends, first record preserved
NAME2="pmxtest-state2-$$"
uv run pmx new --name "${NAME2}" --kind lxc --os rocky --no-domain \
  --cores 1 --memory 512 --disk 8

line_count=$(wc -l < "${LOG}")
test "${line_count}" -eq 2
grep -q "\"hostname\": \"${NAME1}\"" "${LOG}"  # first line preserved
grep -q "\"hostname\": \"${NAME2}\"" "${LOG}"

# Cleanup
uv run pmx destroy "${NAME1}" --yes
uv run pmx destroy "${NAME2}" --yes

echo "State log tests passed."
```

**Verification:**

```bash
chmod +x tests/integration/test_state_log.sh
./tests/integration/test_state_log.sh
```
Expected: all assertions pass, final "State log tests passed."

**Commit:** `docs,test: post-create hook contract doc + state log integration harness`
<!-- END_TASK_3 -->

---

## Phase 8 done when

- Every successful `pmx new` appends one JSON line to `state/guests.jsonl` with `hostname, vmid, mac, ip, kind, os, domain_joined, cephfs_mounts, rbd_disk, extra_packages, static_ip, static_gw, created_at` (AC15.1)
- Second and subsequent builds append without rewriting earlier records (AC15.2)
- A fresh repo with no `state/guests.jsonl` gets the file created on the first build (AC15.3)
- `post_create_hook` role receives the full variable set and its default implementation writes only the state log (AC16.1, AC16.2)
- `docs/extending-post-create.md` exists and documents variables, contract, and how to add a DHCP/DNS integration (AC16.3)
- `tests/integration/test_state_log.sh` passes against the real cluster
- Clean `git status` after commits from Tasks 1–3

---

## Project-level acceptance

With Phase 8 complete, all 16 acceptance criteria from the design are covered across phases. `pmx/verify`, `pmx/destroy`, and `pmx/reconfigure` are fully powered by the state log. The DHCP-reservation extension point is live and documented — any future wiring plugs in under `roles/post_create_hook/tasks/` without touching other code.
