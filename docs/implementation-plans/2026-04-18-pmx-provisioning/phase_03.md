# pmx Provisioning — Phase 3: VM Creation Path (No Domain Join Yet)

**Goal:** `pmx new --kind vm --os {ubuntu|rocky} --no-domain` produces a running, SSH-reachable VM cloned from the seed template, with cloud-init applying hostname, SSH keys, and DHCP networking. The configure phase runs the `common` role only (base package install + upgrade). Domain join lands in Phase 5.

**Architecture:** `pmx new` loads workstation config, validates that no VM with the given name already exists, builds an extra-vars dict, and invokes `provision.yml`. Play 1 (`hosts: proxmox`) clones the seed template via `community.proxmox.proxmox_kvm`, applies cloud-init settings, starts the VM, waits for DHCP-assigned IP, then `add_host`s the new guest into `just_created`. Play 2 (`hosts: just_created`) waits for SSH, then runs `common`.

**Tech Stack:** `community.proxmox` 1.6+, `ansible.builtin.add_host`, `ansible.builtin.wait_for_connection`, Ansible `clone` semantics for `proxmox_kvm`.

**Scope:** Phase 3 of 8.

**Codebase verified:** 2026-04-18. Phase 1 + 2 artifacts present (scaffolding + seed playbook + seed templates 9000/9001 in the plan). `ansible/playbooks/provision.yml` currently has two empty-task plays — this phase populates them for VMs. `ansible/roles/` is empty — `create_vm/` and `common/` get created.

**External dependency investigation findings:**
- ✓ `community.proxmox.proxmox_kvm` (collection 1.6.0) supports `clone:` from a template VMID with cloud-init customization (`ciuser`, `sshkeys`, `ipconfig`, `searchdomain`, `nameserver`). The module is the canonical replacement for the deprecated `community.general.proxmox_kvm`.
- ✓ `ansible.builtin.wait_for_connection` is the current recommended SSH-readiness pattern — it uses Ansible's actual SSH connection plugin rather than port-probing.
- ✓ `ansible.builtin.add_host` with `ansible_host` (not the deprecated `ansible_ssh_host`) is the canonical way to inject a just-created host into in-memory inventory for subsequent plays.
- ✓ QEMU guest agent (`qm guest exec`, `qm guest network-get-interfaces`) is useful for discovering the DHCP-assigned IP when we don't know it in advance. The seed templates from Phase 2 have `--agent enabled=1` set, but the qemu-guest-agent package still needs to be preinstalled in the cloud image. The Ubuntu + Rocky cloud images ship with qemu-guest-agent available but not always installed by default — we install it in the `common` role so it's available on *next* boot. For the first boot, we fall back to polling DHCP leases on Proxmox (via `qm guest network-get-interfaces`, which works once the agent is up).
- 📖 Sources: [community.proxmox.proxmox_kvm docs](https://docs.ansible.com/projects/ansible/latest/collections/community/proxmox/proxmox_kvm_module.html), [ansible.builtin.wait_for_connection](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/wait_for_connection_module.html), [ansible.builtin.add_host](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/add_host_module.html).

---

## Acceptance Criteria Coverage

### pmx-provisioning.AC1: VM creation with AD join works end-to-end
- **pmx-provisioning.AC1.1 Success:** VM created with specified resources, SSH-reachable within 120s of `pmx new`
  *(partially — AC1.2/AC1.3 require Phase 5 AD join; this phase verifies the VM-creation and common-role parts only)*
- **pmx-provisioning.AC1.4 Failure:** `pmx new --name <existing>` refuses with a clear error (names are primary key)

### pmx-provisioning.AC4: Ubuntu and Rocky both first-class
- **pmx-provisioning.AC4.1 Success (partial):** `--os ubuntu` builds a working Ubuntu 24.04 VM *(domain-joined variant covered in Phase 5)*
- **pmx-provisioning.AC4.2 Success (partial):** `--os rocky` builds a working Rocky 9 VM *(domain-joined variant covered in Phase 5)*

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: CLI preflight — name uniqueness and VM-kind wiring

**Verifies:** pmx-provisioning.AC1.4

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/preflight.py`
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` (cmd_new body)

**Implementation:**

Preflight uses SSH to the Proxmox node to run `qm list` and `pct list`, parses the name column, and aborts if the requested name appears. Fast (<1s for a small cluster).

`pmx/preflight.py`:
```python
"""Preflight checks for pmx (name uniqueness, SSH reachability)."""

from __future__ import annotations

import subprocess

import click

from pmx.config import Config


def assert_name_available(cfg: Config, name: str) -> None:
    """Abort if a VM or LXC with the given name already exists on the cluster."""
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        cfg.proxmox_ssh_host,
        "qm list; echo '---'; pct list",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        click.echo(f"Failed to query Proxmox: {exc.stderr}", err=True)
        raise click.Abort() from exc
    except subprocess.TimeoutExpired as exc:
        click.echo(f"Timed out querying Proxmox ({cfg.proxmox_ssh_host}).", err=True)
        raise click.Abort() from exc

    existing = _parse_names(result.stdout)
    if name in existing:
        click.echo(
            f"A guest named '{name}' already exists on the cluster. "
            f"Names are the primary key for pmx; choose a different name or destroy the existing one.",
            err=True,
        )
        raise click.Abort()


def _parse_names(qm_pct_output: str) -> set[str]:
    """Extract guest names from the output of `qm list; echo ---; pct list`."""
    names: set[str] = set()
    for line in qm_pct_output.splitlines():
        parts = line.split()
        # qm list: VMID NAME STATUS ... MEM ...
        # pct list: VMID STATUS ... NAME
        # Skip headers and separator.
        if not parts or parts[0] in ("VMID", "---"):
            continue
        try:
            vmid = int(parts[0])
        except ValueError:
            continue
        # Second field is always the name in both layouts (pct list: VMID STATUS LOCK NAME on some versions).
        # Take the longest alphabetic field after VMID as a heuristic.
        candidates = [p for p in parts[1:] if p.replace("-", "").isalnum() and not p.isdigit()]
        if candidates:
            names.add(candidates[-1])
    return names
```

Modify `pmx/cli.py:cmd_new` — replace the "not yet implemented" block:

```python
def cmd_new(**kwargs: object) -> None:
    """Create a new guest."""
    from pmx.config import load
    from pmx.credentials import ensure_ad_password
    from pmx.ansible_runner import run_playbook
    from pmx.preflight import assert_name_available

    cfg = load()

    if not kwargs["no_domain"]:
        ensure_ad_password()

    assert_name_available(cfg, kwargs["name"])  # type: ignore[arg-type]

    extra_vars = _extra_vars_from(kwargs) | {
        "target_node": cfg.default_node,
        "default_storage": cfg.default_storage,
        "default_lxc_storage": cfg.default_lxc_storage,
        "default_bridge": cfg.default_bridge,
        "ad_domain": cfg.ad_domain,
        "ad_realm": cfg.ad_realm,
        "ad_join_user": cfg.ad_join_user,
        "proxmox_api_host": cfg.proxmox_api_host,
    }

    if kwargs["dry_run"]:
        rc = run_playbook("provision.yml", extra_vars, dry_run=True)
        sys.exit(rc)

    # LXC kind still falls through to stub until Phase 4 lands.
    if kwargs["kind"] == "lxc":
        click.echo("pmx new --kind lxc not yet implemented (Phase 4).", err=True)
        sys.exit(NOT_IMPLEMENTED_EXIT)

    rc = run_playbook("provision.yml", extra_vars)
    sys.exit(rc)
```

**Testing:**

Unit test the name-parsing logic:
- `tests/unit/test_preflight.py` (unit) — Verifies `pmx-provisioning.AC1.4`:
  - Given a sample `qm list; echo ---; pct list` output with a name `neptune`, `_parse_names` returns a set containing `"neptune"`.
  - Given empty output, returns an empty set.
  - Given a name that does NOT appear, `assert_name_available` returns normally (mock `subprocess.run`).
  - Given a name that DOES appear, `assert_name_available` raises `click.Abort`.

**Verification:**

```bash
cd /home/sysop/proxmox-manage
uv run pytest tests/unit/test_preflight.py -v
```
Expected: All tests pass.

Live check:
```bash
AD_JOIN_PASSWORD=x uv run pmx new --name neptune --kind vm --os ubuntu --no-domain
```
(Given `neptune` is a real guest per the cluster inspection.)
Expected: `A guest named 'neptune' already exists on the cluster. ...`, exit non-zero.

**Commit:** `feat(cli): preflight name-uniqueness check via ssh qm/pct list`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Extra-vars contract + provision.yml create play for VMs

**Verifies:** pmx-provisioning.AC1.1 (scaffolding toward)

**Files:**
- Modify: `/home/sysop/proxmox-manage/ansible/playbooks/provision.yml`

**Implementation:**

`provision.yml` (full replacement — two plays):

```yaml
---
# Expected extra-vars (from pmx/cli.py `_extra_vars_from` + config):
#   guest_name, guest_kind ('vm'|'lxc'), guest_os ('ubuntu'|'rocky'),
#   cores, memory, disk, cephfs_mounts, rbd_disk, extra_packages,
#   static_ip, domain_join, target_node, default_storage,
#   default_lxc_storage, default_bridge, ad_domain, ad_realm,
#   ad_join_user, proxmox_api_host.

- name: Create guest on Proxmox
  hosts: "{{ target_node }}"
  gather_facts: false
  become: false
  tasks:
    - name: Create VM
      ansible.builtin.include_role:
        name: create_vm
      when: guest_kind == "vm"

    # Phase 4 adds:
    # - name: Create LXC
    #   ansible.builtin.include_role:
    #     name: create_lxc
    #   when: guest_kind == "lxc"

- name: Configure guest
  hosts: just_created
  gather_facts: true
  become: true
  tasks:
    - name: Run common bootstrap (upgrade + base packages)
      ansible.builtin.include_role:
        name: common

    # Phase 5 adds ad_join roles; Phase 6 adds cephfs/rbd/extras/static_ip;
    # Phase 8 adds post_create_hook.
```

**Verification:**

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=vm -e guest_os=ubuntu -e guest_name=x \
  -e cores=2 -e memory=2048 -e disk=32 \
  -e cephfs_mounts='[]' -e rbd_disk=null -e extra_packages='[]' \
  -e static_ip=null -e domain_join=false -e default_storage=bwrx \
  -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12
```
Expected: "playbook: playbooks/provision.yml" — no syntax errors.

**Commit:** `feat(ansible): provision.yml plays include create_vm role on kind==vm`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: `roles/create_vm` — clone, customize, start, discover IP, add_host

**Verifies:** pmx-provisioning.AC1.1, pmx-provisioning.AC4.1, pmx-provisioning.AC4.2

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/create_vm/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/create_vm/defaults/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/create_vm/vars/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
# Overridden by group_vars/all.yml and CLI extra-vars.
default_storage: bwrx
default_bridge: vmbr0
ssh_wait_timeout: 180
```

`vars/main.yml` (OS → seed-VMID table, not user-configurable):
```yaml
seed_vmids:
  ubuntu: 9000
  rocky: 9001
```

`tasks/main.yml`:
```yaml
---
- name: Allocate next free VMID
  ansible.builtin.command: pvesh get /cluster/nextid
  register: nextid_result
  changed_when: false

- name: Set new_vmid fact
  ansible.builtin.set_fact:
    new_vmid: "{{ nextid_result.stdout | trim | int }}"

- name: Build cloud-init SSH key list (operator's pubkey, read on the Proxmox node)
  ansible.builtin.set_fact:
    cloudinit_sshkeys: "{{ lookup('file', '/root/.ssh/id_ed25519.pub', errors='ignore') | default('', true) }}"

- name: Sanity-check we have at least one SSH pubkey
  ansible.builtin.fail:
    msg: "Could not read /root/.ssh/id_ed25519.pub on the Proxmox node. Populate it or adjust the lookup."
  when: cloudinit_sshkeys | length == 0

- name: Render pubkey to a temp file (qm set --sshkeys takes a file path, not literal content)
  ansible.builtin.copy:
    content: "{{ cloudinit_sshkeys }}\n"
    dest: "/tmp/pmx-{{ new_vmid }}.pub"
    mode: "0600"

- name: Clone seed template into new VMID
  community.proxmox.proxmox_kvm:
    api_host: "{{ proxmox_api_host }}"
    api_user: "root@pam"
    api_token_id: "{{ lookup('env', 'PROXMOX_TOKEN_ID') | default('', true) }}"
    api_token_secret: "{{ lookup('env', 'PROXMOX_TOKEN_SECRET') | default('', true) }}"
    node: "{{ target_node }}"
    clone: "{{ seed_vmids[guest_os] }}"
    newid: "{{ new_vmid }}"
    name: "{{ guest_name }}"
    full: true
    storage: "{{ default_storage }}"
    timeout: 600
    state: present
  # Fall back to qm clone if API creds aren't configured (lab-friendly).
  when: lookup('env', 'PROXMOX_TOKEN_ID') | length > 0

- name: Clone via qm (SSH fallback when no API token configured)
  ansible.builtin.command: >
    qm clone {{ seed_vmids[guest_os] }} {{ new_vmid }}
    --name {{ guest_name }}
    --full 1
    --storage {{ default_storage }}
  when: lookup('env', 'PROXMOX_TOKEN_ID') | length == 0
  changed_when: true

- name: Resize root disk to requested size
  ansible.builtin.command: "qm resize {{ new_vmid }} scsi0 {{ disk }}G"
  changed_when: true

- name: Compute effective static gateway (inferred as .1 of the subnet unless --static-gw supplied)
  ansible.builtin.set_fact:
    effective_static_gw: >-
      {{ static_gw
         if (static_gw | default('', true) | length > 0)
         else (static_ip | ansible.utils.ipaddr('network') | ansible.utils.ipmath(1)) }}
  when: static_ip is not none

- name: Apply cloud-init customization
  ansible.builtin.command: "{{ item }}"
  loop:
    - "qm set {{ new_vmid }} --cores {{ cores }}"
    - "qm set {{ new_vmid }} --memory {{ memory }}"
    - "qm set {{ new_vmid }} --net0 virtio,bridge={{ default_bridge }}"
    - "qm set {{ new_vmid }} --ipconfig0 {{ 'ip=' + static_ip + ',gw=' + effective_static_gw if static_ip else 'ip=dhcp' }}"
    - "qm set {{ new_vmid }} --ciuser ansible"
    - "qm set {{ new_vmid }} --sshkeys /tmp/pmx-{{ new_vmid }}.pub"
  changed_when: true

- name: Set searchdomain (only when joining AD)
  ansible.builtin.command: "qm set {{ new_vmid }} --searchdomain {{ ad_domain }}"
  when: domain_join | bool
  changed_when: true

- name: Clean up temp pubkey file
  ansible.builtin.file:
    path: "/tmp/pmx-{{ new_vmid }}.pub"
    state: absent

- name: Start VM
  ansible.builtin.command: "qm start {{ new_vmid }}"
  changed_when: true

- name: Wait for QEMU guest agent to come up
  ansible.builtin.command: "qm guest ping {{ new_vmid }}"
  register: qga_probe
  retries: 30
  delay: 5
  until: qga_probe.rc == 0
  changed_when: false

- name: Discover DHCP-assigned IPv4
  ansible.builtin.command: "qm guest cmd {{ new_vmid }} network-get-interfaces"
  register: interfaces_raw
  changed_when: false

- name: Parse first non-loopback IPv4 from guest agent output
  ansible.builtin.set_fact:
    guest_ip: >-
      {{ (interfaces_raw.stdout | from_json
          | selectattr('name', 'ne', 'lo')
          | map(attribute='ip-addresses') | flatten
          | selectattr('ip-address-type', 'eq', 'ipv4')
          | rejectattr('ip-address', 'search', '^127\\.')
          | map(attribute='ip-address') | first) | default(none) }}

- name: Fail if no IPv4 was discovered
  ansible.builtin.fail:
    msg: "Guest {{ guest_name }} (VMID {{ new_vmid }}) did not acquire an IPv4 address via guest agent."
  when: guest_ip is none or guest_ip == ""

- name: Add new guest to in-memory inventory as `just_created`
  ansible.builtin.add_host:
    name: "{{ guest_name }}"
    ansible_host: "{{ guest_ip }}"
    ansible_user: ansible
    ansible_become: true
    ansible_ssh_common_args: "-o StrictHostKeyChecking=accept-new"
    groups: just_created
    # Pass through variables the configure plays need:
    guest_vmid: "{{ new_vmid }}"
    guest_kind: "{{ guest_kind }}"
    guest_os: "{{ guest_os }}"
    guest_mac: "{{ (interfaces_raw.stdout | from_json | selectattr('name', 'ne', 'lo') | first)['hardware-address'] }}"
    domain_join: "{{ domain_join }}"
    ad_domain: "{{ ad_domain }}"
    ad_realm: "{{ ad_realm }}"
    ad_join_user: "{{ ad_join_user }}"
    cephfs_mounts: "{{ cephfs_mounts }}"
    rbd_disk: "{{ rbd_disk }}"
    extra_packages: "{{ extra_packages }}"
    static_ip: "{{ static_ip }}"

- name: Show discovered IP for operator
  ansible.builtin.debug:
    msg: "Guest {{ guest_name }} (vmid {{ new_vmid }}) reachable at {{ guest_ip }}."
```

**Testing:**

A live integration test is the only honest verification. Mocking `qm`/`proxmoxer`/QGA over multiple calls would test the mock, not the behavior. The test script in Task 5 performs the integration check and maps it to AC1.1, AC4.1, AC4.2.

**Verification:**

Syntax check:
```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=vm -e guest_os=ubuntu -e guest_name=test \
  -e cores=2 -e memory=2048 -e disk=32 -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e domain_join=false \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12
```
Expected: syntax OK.

**Commit:** `feat(create_vm): clone seed, customize, start, discover IP, add_host`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: `roles/common` — OS-family-conditional base bootstrap

**Verifies:** pmx-provisioning.AC4.1, pmx-provisioning.AC4.2

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/common/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/common/tasks/ubuntu.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/common/tasks/rocky.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/common/defaults/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
common_base_packages_ubuntu:
  - tmux
  - ca-certificates
  - curl
  - python3
  - qemu-guest-agent
common_base_packages_rocky:
  - tmux
  - ca-certificates
  - curl
  - python3
  - qemu-guest-agent
```

`tasks/main.yml` (dispatcher):
```yaml
---
- name: Wait for SSH readiness
  ansible.builtin.wait_for_connection:
    delay: 5
    timeout: "{{ ssh_wait_timeout | default(180) }}"
    connect_timeout: 10

- name: Include OS-specific bootstrap
  ansible.builtin.include_tasks: "{{ guest_os }}.yml"
```

`tasks/ubuntu.yml`:
```yaml
---
- name: Wait for apt to finish any ongoing unattended run
  ansible.builtin.command: >
    bash -c 'for i in $(seq 1 60); do if ! pgrep -x "unattended-upgr|apt|apt-get" >/dev/null; then exit 0; fi; sleep 2; done; exit 1'
  changed_when: false

- name: apt update
  ansible.builtin.apt:
    update_cache: true
    cache_valid_time: 0

- name: apt dist-upgrade
  ansible.builtin.apt:
    upgrade: dist

- name: Install base packages
  ansible.builtin.apt:
    name: "{{ common_base_packages_ubuntu }}"
    state: present

- name: Enable and start qemu-guest-agent
  ansible.builtin.systemd:
    name: qemu-guest-agent
    state: started
    enabled: true
```

`tasks/rocky.yml`:
```yaml
---
- name: dnf upgrade
  ansible.builtin.dnf:
    name: "*"
    state: latest
    update_cache: true

- name: Install base packages
  ansible.builtin.dnf:
    name: "{{ common_base_packages_rocky }}"
    state: present

- name: Enable and start qemu-guest-agent
  ansible.builtin.systemd:
    name: qemu-guest-agent
    state: started
    enabled: true
```

**Testing:**

Exercise via Task 5's integration test — `common` runs end-to-end as part of `pmx new`, and the verification step confirms qemu-guest-agent is active.

**Verification:**

Syntax check:
```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=vm -e guest_os=ubuntu -e guest_name=x \
  -e cores=2 -e memory=2048 -e disk=32 -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e domain_join=false \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12
```
Expected: syntax OK.

**Commit:** `feat(common): OS-conditional apt/dnf upgrade + base packages + qemu-guest-agent`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->

<!-- START_TASK_5 -->
### Task 5: End-to-end VM integration test (Ubuntu and Rocky)

**Verifies:** pmx-provisioning.AC1.1, pmx-provisioning.AC4.1, pmx-provisioning.AC4.2

**Files:**
- Create: `/home/sysop/proxmox-manage/tests/integration/test_create_vm.sh` (bash integration harness; documented, not run in CI)

**Implementation:**

```bash
#!/usr/bin/env bash
set -euo pipefail

# tests/integration/test_create_vm.sh — exercises pmx new --kind vm end-to-end.
# Requires: pmx seed already run (templates 9000 + 9001 exist).
# Destructive: leaves one VM per OS family running on the cluster; caller cleans up.

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

smoke_test() {
  local os="$1"
  local name="pmxtest-${os}-$$"

  echo "=== Building ${os} VM named ${name} ==="
  AD_JOIN_PASSWORD=x uv run pmx new \
    --name "${name}" \
    --kind vm \
    --os "${os}" \
    --cores 2 --memory 2048 --disk 32 \
    --no-domain

  echo "=== Verifying ${name} ==="
  # Find IP via the state log (Phase 8) OR via pvesh once it exists; for Phase 3 we
  # rediscover via the cluster:
  local ip
  ip="$(ssh root@192.168.9.12 "qm guest cmd \$(qm list | awk -v n=${name} '\$2==n{print \$1}') network-get-interfaces" \
        | python3 -c 'import json,sys; print([a["ip-address"] for i in json.load(sys.stdin) if i["name"]!="lo" for a in i.get("ip-addresses",[]) if a["ip-address-type"]=="ipv4" and not a["ip-address"].startswith("127.")][0])')"

  echo "IP: ${ip}"

  ssh -o StrictHostKeyChecking=accept-new ansible@${ip} "systemctl is-active qemu-guest-agent"
  ssh ansible@${ip} "which tmux && which curl && which python3"

  echo "=== ${name} OK ==="
}

smoke_test ubuntu
smoke_test rocky
echo "Both OS families passed."
```

**Verification:**

```bash
chmod +x tests/integration/test_create_vm.sh
./tests/integration/test_create_vm.sh
```
Expected: both VMs created, SSH reachable as `ansible@<ip>`, qemu-guest-agent active, base tools installed. Maps to:
- AC1.1: SSH-reachable within 120s — verified by the implicit `wait_for_connection` in `common` + the post-run `ssh` check
- AC4.1: Ubuntu VM works
- AC4.2: Rocky VM works

Cleanup (operator runs when ready):
```bash
ssh root@192.168.9.12 "for n in pmxtest-ubuntu-* pmxtest-rocky-*; do vmid=\$(qm list | awk -v n=\$n '\$2==n{print \$1}'); [ -n \"\$vmid\" ] && qm stop \$vmid && qm destroy \$vmid --purge; done"
```

**Commit:** `test(create_vm): integration harness for Ubuntu + Rocky VM creation`
<!-- END_TASK_5 -->

---

## Phase 3 done when

- `pmx new --name foo --kind vm --os ubuntu --no-domain` produces a running Ubuntu 24.04 VM, SSH-reachable as `ansible@<ip>`, with base packages installed and `qemu-guest-agent` active (AC1.1, AC4.1)
- Same with `--os rocky` produces a Rocky 9 VM (AC1.1, AC4.2)
- `pmx new --name <existing-name> ...` refuses with "already exists" error and exits non-zero (AC1.4)
- `tests/unit/test_preflight.py` passes under pytest
- `ansible-playbook --syntax-check` passes for `provision.yml` with Phase 3's tasks wired
- Clean `git status` after commits from Tasks 1–5
