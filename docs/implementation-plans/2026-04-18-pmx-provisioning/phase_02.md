# pmx Provisioning — Phase 2: `pmx seed` Bootstrap

**Goal:** `pmx seed` downloads the Ubuntu 24.04 and Rocky 9 cloud images, builds cloud-init-ready VM templates on the cluster, and pulls the Rocky LXC template. Idempotent — re-running skips what already exists.

**Architecture:** `pmx seed` shells out to `ansible/playbooks/seed.yml`, which runs three roles against the configured Proxmox node (`default_node` from config). Each role checks whether its output already exists before doing any work. VM templates are assigned fixed seed VMIDs (`9000` Ubuntu, `9001` Rocky) so re-runs and subsequent clones have a stable handle.

**Tech Stack:** Ansible core 2.17+, `ansible.builtin.get_url` / `ansible.builtin.command` / `ansible.builtin.stat`. Proxmox 8.2.4 `qm` + `pveam`.

**Scope:** Phase 2 of 8.

**Codebase verified:** 2026-04-18. None of the seed-related files or roles exist. Phase 1 leaves `ansible/playbooks/provision.yml` as an empty skeleton and inventory/group_vars in place — we build on that.

**External dependency investigation findings:**
- ✓ Ubuntu 24.04 cloud image canonical URL: `https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img`
- ✓ Rocky 9 cloud image canonical URL pattern: `https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base-9.latest.x86_64.qcow2` (versioned release filenames also fine)
- ✓ Proxmox 8.2 template build sequence per official wiki: `qm create` → `qm importdisk` → set `scsihw virtio-scsi-pci`, `scsi0`, `ide2 cloudinit`, `boot c`, `bootdisk scsi0`, `serial0 socket`, `vga serial0` → `qm template`
- ✓ `pveam available --section system | grep rockylinux` returns entries like `rockylinux-9-default_20240904_amd64.tar.xz`; `pveam download cephfs <name>` is idempotent if already present
- ✓ Storage: user's cluster has `bwrx` (RBD) for VM disks and `cephfs` for LXC templates / ISO-like content (verified in cluster inspection during design)
- 📖 Sources: [Proxmox Cloud-Init wiki](https://pve.proxmox.com/wiki/Cloud-Init_Support), [Ubuntu cloud images](https://cloud-images.ubuntu.com/noble/current/), [Rocky images](https://dl.rockylinux.org/pub/rocky/9/images/x86_64/)

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pmx-provisioning.AC6: pmx seed bootstrap
- **pmx-provisioning.AC6.1 Success:** Empty cluster produces one Ubuntu VM template, one Rocky VM template, and the Rocky LXC template cached
- **pmx-provisioning.AC6.2 Success:** Re-running `pmx seed` is a no-op (idempotent)
- **pmx-provisioning.AC6.3 Edge:** Partial prior state (e.g., only Ubuntu template exists) completes only the missing work

---

<!-- START_TASK_1 -->
### Task 1: Wire `pmx seed` CLI to the seed playbook

**Verifies:** pmx-provisioning.AC6.1 (end-to-end invocation)

**Files:**
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` (replace stub in `cmd_seed`)
- Create: `/home/sysop/proxmox-manage/pmx/seed.py`

**Implementation:**

`pmx/seed.py` — orchestrator, loads config and passes the resolved Proxmox SSH alias into the playbook run:

```python
"""pmx seed — build base VM templates and pull LXC templates on the cluster."""

from __future__ import annotations

import click

from pmx.ansible_runner import run_playbook
from pmx.config import load


def run() -> int:
    cfg = load()
    extra_vars = {
        "target_node": cfg.default_node,
        "default_storage": cfg.default_storage,
        "default_lxc_storage": cfg.default_lxc_storage,
        "default_bridge": cfg.default_bridge,
    }
    click.echo(f"Seeding templates on node {cfg.default_node}...", err=True)
    return run_playbook("seed.yml", extra_vars)
```

Modify `pmx/cli.py:cmd_seed` (replace body):

```python
@main.command("seed")
def cmd_seed() -> None:
    """Download and build base VM + LXC templates on the cluster."""
    from pmx import seed

    sys.exit(seed.run())
```

**Verification:**

Task 6 covers end-to-end. For this task, a syntax-only check:

```bash
cd /home/sysop/proxmox-manage
uv run pmx seed --help
```
Expected: Help text (no flags, just description). Exit 0.

```bash
uv run python -c "from pmx import seed; print(seed.run)"
```
Expected: `<function run at 0x...>`.

**Commit:** `feat(seed): wire pmx seed CLI to the seed.yml playbook`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: `ansible/playbooks/seed.yml` top-level playbook

**Verifies:** pmx-provisioning.AC6.1

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/playbooks/seed.yml`

**Implementation:**

Single play targeting the user-selected node (from `target_node` extra-var, constrained to the `proxmox` group). Runs three roles; order doesn't matter — each is independently idempotent.

```yaml
---
- name: Seed Proxmox templates
  hosts: "{{ target_node }}"
  gather_facts: false
  become: false
  vars:
    ubuntu_template_vmid: 9000
    ubuntu_template_name: template-ubuntu-2404
    ubuntu_image_url: https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
    ubuntu_image_checksum_url: https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
    rocky_template_vmid: 9001
    rocky_template_name: template-rocky-9
    rocky_image_url: https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2
    rocky_lxc_template_name_pattern: "rockylinux-9-default_*_amd64.tar.xz"
    image_cache_dir: /var/lib/vz/template/iso
  roles:
    - role: seed_ubuntu_vm
    - role: seed_rocky_vm
    - role: seed_rocky_lxc
```

**Verification:**

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/seed.yml -e target_node=pve01
```
Expected: No syntax errors.

**Commit:** `feat(seed): add seed.yml playbook referencing three seed roles`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: `roles/seed_ubuntu_vm` — download + build Ubuntu 24.04 template

**Verifies:** pmx-provisioning.AC6.1, pmx-provisioning.AC6.2, pmx-provisioning.AC6.3

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/seed_ubuntu_vm/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/seed_ubuntu_vm/defaults/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
ubuntu_template_vmid: 9000
ubuntu_template_name: template-ubuntu-2404
ubuntu_image_url: https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
image_cache_dir: /var/lib/vz/template/iso
default_storage: bwrx
default_bridge: vmbr0
```

`tasks/main.yml`:
```yaml
---
- name: Check if Ubuntu template already exists
  ansible.builtin.command: qm status {{ ubuntu_template_vmid }}
  register: ubuntu_template_probe
  changed_when: false
  failed_when: false

- name: Skip rest of role when template already exists
  ansible.builtin.meta: end_host
  when: ubuntu_template_probe.rc == 0

- name: Ensure image cache dir exists
  ansible.builtin.file:
    path: "{{ image_cache_dir }}"
    state: directory
    mode: "0755"

- name: Download Ubuntu cloud image
  ansible.builtin.get_url:
    url: "{{ ubuntu_image_url }}"
    dest: "{{ image_cache_dir }}/noble-server-cloudimg-amd64.img"
    mode: "0644"
    timeout: 600

- name: Create VM shell for template
  ansible.builtin.command: >
    qm create {{ ubuntu_template_vmid }}
    --name {{ ubuntu_template_name }}
    --memory 2048 --cores 2
    --net0 virtio,bridge={{ default_bridge }}
    --ostype l26
  changed_when: true

- name: Import disk into storage
  ansible.builtin.command: >
    qm importdisk {{ ubuntu_template_vmid }}
    {{ image_cache_dir }}/noble-server-cloudimg-amd64.img
    {{ default_storage }}
  changed_when: true

- name: Attach disk, cloud-init drive, serial console
  ansible.builtin.command: "{{ item }}"
  loop:
    - "qm set {{ ubuntu_template_vmid }} --scsihw virtio-scsi-pci --scsi0 {{ default_storage }}:vm-{{ ubuntu_template_vmid }}-disk-0"
    - "qm set {{ ubuntu_template_vmid }} --ide2 {{ default_storage }}:cloudinit"
    - "qm set {{ ubuntu_template_vmid }} --boot c --bootdisk scsi0"
    - "qm set {{ ubuntu_template_vmid }} --serial0 socket --vga serial0"
    - "qm set {{ ubuntu_template_vmid }} --agent enabled=1"
  changed_when: true

- name: Convert to template
  ansible.builtin.command: qm template {{ ubuntu_template_vmid }}
  changed_when: true
```

Note on idempotency: `end_host` short-circuits when the VM already exists. For partial failures (VM exists but isn't a template), the operator destroys it manually and re-runs — our "keep it simple" stance; auto-repair would be high-risk for a one-shot bootstrap.

**Verification:**

Integration test (requires real Proxmox):
```bash
cd /home/sysop/proxmox-manage/ansible
ssh root@192.168.9.12 "qm destroy 9000 --purge || true"
uv run ansible-playbook playbooks/seed.yml -e target_node=pve01 --tags seed_ubuntu_vm \
  || uv run ansible-playbook playbooks/seed.yml -e target_node=pve01
ssh root@192.168.9.12 "qm list | grep 9000"
```
Expected: `9000 template-ubuntu-2404 stopped  ...`

Re-run idempotency:
```bash
uv run ansible-playbook playbooks/seed.yml -e target_node=pve01
```
Expected: Play runs, Ubuntu role short-circuits via `end_host`, no changes reported against `qm`.

**Commit:** `feat(seed): add seed_ubuntu_vm role for Ubuntu 24.04 template`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: `roles/seed_rocky_vm` — download + build Rocky 9 template

**Verifies:** pmx-provisioning.AC6.1, pmx-provisioning.AC6.2, pmx-provisioning.AC6.3

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/seed_rocky_vm/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/seed_rocky_vm/defaults/main.yml`

**Implementation:**

Structurally identical to `seed_ubuntu_vm` with different VMID/name/URL. The `.latest.` URL pattern pulls whatever Rocky has tagged current.

`defaults/main.yml`:
```yaml
rocky_template_vmid: 9001
rocky_template_name: template-rocky-9
rocky_image_url: https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2
image_cache_dir: /var/lib/vz/template/iso
default_storage: bwrx
default_bridge: vmbr0
```

`tasks/main.yml`: same structure as seed_ubuntu_vm but substitute:
- `rocky_template_vmid` everywhere
- image filename: `rocky-9-genericcloud.qcow2`
- import command points at the rocky qcow2
- VM name: `{{ rocky_template_name }}`

```yaml
---
- name: Check if Rocky template already exists
  ansible.builtin.command: qm status {{ rocky_template_vmid }}
  register: rocky_template_probe
  changed_when: false
  failed_when: false

- name: Skip rest of role when template already exists
  ansible.builtin.meta: end_host
  when: rocky_template_probe.rc == 0

- name: Ensure image cache dir exists
  ansible.builtin.file:
    path: "{{ image_cache_dir }}"
    state: directory
    mode: "0755"

- name: Download Rocky cloud image
  ansible.builtin.get_url:
    url: "{{ rocky_image_url }}"
    dest: "{{ image_cache_dir }}/rocky-9-genericcloud.qcow2"
    mode: "0644"
    timeout: 600

- name: Create VM shell for template
  ansible.builtin.command: >
    qm create {{ rocky_template_vmid }}
    --name {{ rocky_template_name }}
    --memory 2048 --cores 2
    --net0 virtio,bridge={{ default_bridge }}
    --ostype l26
  changed_when: true

- name: Import disk into storage
  ansible.builtin.command: >
    qm importdisk {{ rocky_template_vmid }}
    {{ image_cache_dir }}/rocky-9-genericcloud.qcow2
    {{ default_storage }}
  changed_when: true

- name: Attach disk, cloud-init drive, serial console
  ansible.builtin.command: "{{ item }}"
  loop:
    - "qm set {{ rocky_template_vmid }} --scsihw virtio-scsi-pci --scsi0 {{ default_storage }}:vm-{{ rocky_template_vmid }}-disk-0"
    - "qm set {{ rocky_template_vmid }} --ide2 {{ default_storage }}:cloudinit"
    - "qm set {{ rocky_template_vmid }} --boot c --bootdisk scsi0"
    - "qm set {{ rocky_template_vmid }} --serial0 socket --vga serial0"
    - "qm set {{ rocky_template_vmid }} --agent enabled=1"
  changed_when: true

- name: Convert to template
  ansible.builtin.command: qm template {{ rocky_template_vmid }}
  changed_when: true
```

**Verification:**

```bash
ssh root@192.168.9.12 "qm destroy 9001 --purge || true"
uv run ansible-playbook playbooks/seed.yml -e target_node=pve01
ssh root@192.168.9.12 "qm list | grep 9001"
```
Expected: `9001 template-rocky-9 stopped  ...`

Re-run for idempotency, expect no changes.

**Commit:** `feat(seed): add seed_rocky_vm role for Rocky 9 template`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: `roles/seed_rocky_lxc` — pull Rocky 9 LXC template

**Verifies:** pmx-provisioning.AC6.1, pmx-provisioning.AC6.2, pmx-provisioning.AC6.3

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/seed_rocky_lxc/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/seed_rocky_lxc/defaults/main.yml`

**Implementation:**

`pveam` hosts the available system templates; we select the latest Rocky 9 entry. Re-running is inexpensive (`pveam download` skips if the file is present on the target storage).

`defaults/main.yml`:
```yaml
default_lxc_storage: cephfs
rocky_lxc_template_pattern: "^rockylinux-9-default_.*_amd64\\.tar\\.xz$"
```

`tasks/main.yml`:
```yaml
---
- name: Refresh pveam catalog
  ansible.builtin.command: pveam update
  changed_when: false

- name: List available Rocky 9 LXC templates
  ansible.builtin.command: pveam available --section system
  register: pveam_available
  changed_when: false

- name: Pick latest Rocky 9 LXC template filename
  ansible.builtin.set_fact:
    rocky_lxc_template: >-
      {{ (pveam_available.stdout_lines
          | select('match', rocky_lxc_template_pattern)
          | map('regex_replace', '^.*\\s', '')
          | list
          | sort
          | last) | default(None) }}

- name: Fail if no Rocky 9 LXC template is listed
  ansible.builtin.fail:
    msg: "No Rocky 9 LXC template found in `pveam available --section system`."
  when: rocky_lxc_template is none or rocky_lxc_template == ""

- name: Check whether template is already downloaded
  ansible.builtin.command: "pveam list {{ default_lxc_storage }}"
  register: pveam_list
  changed_when: false

- name: Download Rocky 9 LXC template
  ansible.builtin.command: "pveam download {{ default_lxc_storage }} {{ rocky_lxc_template }}"
  when: rocky_lxc_template not in pveam_list.stdout
  changed_when: true
```

**Verification:**

```bash
ssh root@192.168.9.12 "pveam list cephfs | grep -E 'rockylinux-9' || true"
uv run ansible-playbook playbooks/seed.yml -e target_node=pve01
ssh root@192.168.9.12 "pveam list cephfs | grep rockylinux-9"
```
Expected: The downloaded template appears in the listing.

Re-run idempotency:
```bash
uv run ansible-playbook playbooks/seed.yml -e target_node=pve01
```
Expected: `pveam list` changed=0, no second download.

**Commit:** `feat(seed): add seed_rocky_lxc role to pull Rocky 9 LXC template via pveam`
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: End-to-end verification

**Verifies:** pmx-provisioning.AC6.1, pmx-provisioning.AC6.2, pmx-provisioning.AC6.3

**Files:** none (test only).

**Implementation:**

Exercise the `pmx seed` command against the real cluster. This is a manual integration check, not an automated test — treat it as acceptance evidence that the three roles work together.

**Verification:**

```bash
# Clean slate (destructive! run on a lab cluster only)
ssh root@192.168.9.12 "qm destroy 9000 --purge 2>/dev/null || true; qm destroy 9001 --purge 2>/dev/null || true"

cd /home/sysop/proxmox-manage
uv run pmx seed
```
Expected: Ubuntu + Rocky templates created, Rocky LXC template downloaded. Playbook exits 0.

```bash
ssh root@192.168.9.12 'qm list | grep -E "^\s+900[01]"; pveam list cephfs | grep rockylinux'
```
Expected: `9000 template-ubuntu-2404 stopped`, `9001 template-rocky-9 stopped`, plus the Rocky LXC `.tar.xz` entry.

**AC6.2 — idempotency:**
```bash
uv run pmx seed
```
Expected: Playbook exits 0, `changed=0` for the Ubuntu and Rocky VM sections (due to `end_host`), and `changed=0` for the LXC section (template already present).

**AC6.3 — partial state:**
```bash
ssh root@192.168.9.12 "qm destroy 9001 --purge"
uv run pmx seed
```
Expected: Ubuntu role skips (exists), Rocky role rebuilds 9001, LXC role skips (present).

**Commit:** No commit — test only.
<!-- END_TASK_6 -->

---

## Phase 2 done when

- `pmx seed` on an empty cluster builds both VM templates and pulls the Rocky LXC template (AC6.1)
- Re-running `pmx seed` exits 0 with zero changes on a fully-seeded cluster (AC6.2)
- Re-running after manually destroying only one template rebuilds only that one (AC6.3)
- All three role dirs exist with `tasks/main.yml` + `defaults/main.yml`
- `ansible-playbook --syntax-check playbooks/seed.yml` passes
- Clean `git status` after commits from Tasks 1–5
