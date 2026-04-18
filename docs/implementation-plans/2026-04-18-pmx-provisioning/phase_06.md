# pmx Provisioning — Phase 6: Build Options (CephFS, RBD, Extras, Static IP)

**Goal:** The four additional build-time options work on both kinds and both OS families: `--cephfs` (VM native mount / LXC passthrough), `--rbd-disk` (VM only), `--extra-packages` (OS-conditional), and `--static-ip` (with corrected gateway handling introduced in this phase).

**Architecture:** Three new configure-phase roles wire into `provision.yml`'s configure play, each guarded by a presence check on the relevant extra-var:
- `mount_cephfs` — branches on `guest_kind`. VM: installs `ceph-common`, drops `/etc/ceph/ceph.conf` + `cephfs.secret`, writes fstab entries, runs `mount -a`. LXC: host-side mount on the Proxmox node (idempotent against existing mounts), patches `/etc/pve/lxc/<vmid>.conf` with `mp<N>:` pass-through lines, restarts the container if necessary.
- `attach_rbd_disk` — VM-only; `qm set <vmid> --scsi1 <pool>:<size>` (`community.proxmox.proxmox_disk` does not exist as of 2026, so raw `qm set` is the implementation).
- `extra_packages` — small wrapper that selects apt vs dnf based on `guest_os` and installs the operator-supplied list.

Additionally, this phase **corrects and completes** the `--static-ip` plumbing: Phase 3/4 wired an inline expression that attempts to infer the gateway but the Jinja expression is fragile. We introduce an explicit `--static-gw` CLI flag (optional override) with a safe default of "first usable IP in the subnet" (i.e. `.1`).

**Tech Stack:** Ansible `mount`, `blockinfile`, `copy`, `apt` / `dnf`, `ansible.utils.ipaddr` filter.

**Scope:** Phase 6 of 8.

**Codebase verified:** 2026-04-18. Phase 1–5 artifacts in place. `ansible/roles/` now has `create_vm/`, `create_lxc/`, `common/`, `ad_join_common/`, `ad_join_ubuntu/`, `ad_join_rocky/`. Host `/etc/ceph/ceph.conf` and `/etc/ceph/cephfs.secret` are present on the workstation (mode 0644; we'll re-tighten to 0600 as we copy into guests). Cluster RBD pool `bwrx` confirmed from earlier inspection.

**External dependency investigation findings:**
- ✓ `community.posix.mount` (part of `ansible.posix`) handles fstab + mount idempotently; already pulled in by Phase 1's `requirements.yml`.
- ✓ CephFS kernel mount syntax unchanged: `name=admin,secretfile=/etc/ceph/cephfs.secret,noatime,_netdev`. Mon list in `sources`: `192.168.9.11,192.168.9.12,192.168.9.13,192.168.9.14:6789:/subpath` as the first column of fstab.
- ✓ Ubuntu 24.04 `ceph-common` is in the distro repos (Reef-compatible).
- ⚠ Rocky 9 `ceph-common` requires the upstream `ceph.repo`; we ship it from a templated `.repo` file. Some 2025 reports flag OpenSSL 3.4.0 dependency issues on Rocky 9.6; mitigation is pinning to an earlier Ceph release or using the distro's Storage SIG packages. Implement with a warning note; if a site hits the dep issue, they pin manually.
- ✓ LXC mp syntax: `mp0: /host/path,mp=/guest/path,ro=0`. Up to 256 mountpoints supported. Adding after create requires container restart.
- ✓ `community.proxmox.proxmox_disk` does **not** exist as of collection 1.6.x. Raw `qm set <vmid> --scsiN <pool>:<size>` is the canonical approach.
- ✓ Cloud-init `ipconfig0=ip=192.168.9.80/24,gw=192.168.9.1` is current format.
- 📖 Sources: [Proxmox wiki: Linux Container](https://pve.proxmox.com/wiki/Linux_Container), [community.posix.mount](https://docs.ansible.com/projects/ansible/latest/collections/community/posix/mount_module.html), [CephFS kernel client](https://docs.ceph.com/en/reef/cephfs/mount-using-kernel-driver/).

---

## Acceptance Criteria Coverage

### pmx-provisioning.AC2: Unprivileged LXC with UID-map fix
- **pmx-provisioning.AC2.3 Success:** Ceph pass-through mounts are visible in the LXC at the declared path

### pmx-provisioning.AC8: --cephfs mount option
- **pmx-provisioning.AC8.1 Success:** VM: ceph-common installed, fstab entry added, mount live at specified path, survives reboot
- **pmx-provisioning.AC8.2 Success:** LXC: path mounted on host (if not already), `mp<N>:` pass-through line added to container config; no ceph-common installed inside
- **pmx-provisioning.AC8.3 Edge:** Host-side mount already present — role is idempotent
- **pmx-provisioning.AC8.4 Failure:** Missing `/etc/ceph/cephfs.secret` on workstation fails with actionable error

### pmx-provisioning.AC9: --rbd-disk option
- **pmx-provisioning.AC9.1 Success:** VM gets an extra RBD-backed disk from pool `bwrx` at requested size
- **pmx-provisioning.AC9.2 Failure:** `--rbd-disk` combined with `--kind lxc` fails fast with "VM only" error

### pmx-provisioning.AC10: --extra-packages
- **pmx-provisioning.AC10.1 Success:** Packages installed on Ubuntu via apt; on Rocky via dnf
- **pmx-provisioning.AC10.2 Failure:** Unknown package name surfaces package-manager error with vmid context

### pmx-provisioning.AC11: --static-ip (default DHCP)
- **pmx-provisioning.AC11.1 Success:** VM boots with specified static IP/CIDR
- **pmx-provisioning.AC11.2 Success:** LXC boots with specified static IP
- **pmx-provisioning.AC11.3 Default:** Absence of flag keeps DHCP behavior

---

<!-- START_TASK_1 -->
### Task 1: Add `--static-gw` CLI flag; reject `--rbd-disk` with `--kind lxc`

**Verifies:** pmx-provisioning.AC9.2, pmx-provisioning.AC11.1, pmx-provisioning.AC11.2, pmx-provisioning.AC11.3

**Files:**
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` — add `--static-gw` flag; extend `_extra_vars_from` to pass it through; add CLI validation that rejects `--rbd-disk` with `--kind lxc`

**Implementation notes:**

Phase 3 Task 3 and Phase 4 Task 2 already compute `effective_static_gw` correctly from `static_ip` using `ansible.utils.ipaddr('network') | ansible.utils.ipmath(1)`, with `static_gw | default('', true)` guarding against the variable being unset or empty. So all this task needs to do is (a) make `--static-gw` actually reachable from the CLI and (b) pipe it into the extra-vars dict so the Ansible-side expression picks it up when the operator supplies it. Plus the `--rbd-disk + lxc` rejection.

**Step 1: Add `--static-gw` to `cmd_new`**

Add a new Click option directly above `--no-domain`:
```python
@click.option(
    "--static-gw",
    default=None,
    help="Gateway IP for --static-ip (default: first usable IP in the subnet, e.g. .1 for /24).",
)
```

**Step 2: Reject `--rbd-disk + --kind lxc` in `cmd_new` body**

Right after the `ensure_ad_password` call and before `assert_name_available`:
```python
if kwargs["rbd_disk"] is not None and kwargs["kind"] == "lxc":
    click.echo("--rbd-disk is VM-only; --kind lxc cannot attach raw RBD disks.", err=True)
    sys.exit(2)
```

**Step 3: Extend `_extra_vars_from`**

Add `static_gw` beside `static_ip`:
```python
"static_ip": kwargs["static_ip"],
"static_gw": kwargs["static_gw"],
```

**Testing:**

Unit test the CLI rejection path (`tests/unit/test_cli.py`) — Verifies `pmx-provisioning.AC9.2`:
- Invoking `pmx new --name x --kind lxc --os ubuntu --rbd-disk 10 --no-domain` exits 2 with the expected error message.
- Invoking `pmx new --name x --kind vm --os ubuntu --rbd-disk 10 --no-domain --dry-run` prints the ansible command and exits 0.

Use Click's `CliRunner` to test without live Proxmox:
```python
from click.testing import CliRunner
from pmx.cli import main

def test_rbd_disk_rejects_lxc():
    result = CliRunner().invoke(main, [
        "new", "--name", "x", "--kind", "lxc", "--os", "ubuntu",
        "--rbd-disk", "10", "--no-domain",
    ])
    assert result.exit_code == 2
    assert "VM-only" in result.output
```

**Verification:**

```bash
cd /home/sysop/proxmox-manage
uv run pytest tests/unit/test_cli.py -v
```
Expected: test_rbd_disk_rejects_lxc passes.

Live inference check — a build without `--static-gw` but with `--static-ip 192.168.9.80/24` should produce `ipconfig0=ip=192.168.9.80/24,gw=192.168.9.1` on the cloud-init drive. Covered in Task 5 integration test (which must include at least one case that omits `--static-gw`).

**Commit:** `feat(cli): add --static-gw flag; reject --rbd-disk with --kind lxc`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: `roles/mount_cephfs` — VM-native mount and LXC passthrough

**Verifies:** pmx-provisioning.AC2.3, pmx-provisioning.AC8.1, pmx-provisioning.AC8.2, pmx-provisioning.AC8.3, pmx-provisioning.AC8.4

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/mount_cephfs/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/mount_cephfs/tasks/vm.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/mount_cephfs/tasks/lxc.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/mount_cephfs/defaults/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/mount_cephfs/templates/ceph.client.admin.keyring.j2`

**Implementation:**

`defaults/main.yml`:
```yaml
ceph_conf_path: /etc/ceph/ceph.conf
ceph_secret_path: /etc/ceph/cephfs.secret
ceph_mons:
  - 192.168.9.11
  - 192.168.9.12
  - 192.168.9.13
  - 192.168.9.14
cephfs_mount_opts: "name=admin,secretfile=/etc/ceph/cephfs.secret,noatime,_netdev"
```

`tasks/main.yml`:
```yaml
---
- name: Short-circuit if no CephFS mounts requested
  ansible.builtin.meta: end_host
  when: cephfs_mounts | default([]) | length == 0

- name: Parse cephfs_mounts into structured list
  ansible.builtin.set_fact:
    cephfs_specs: "{{ cephfs_mounts | map('pmx_parse_cephfs') | list }}"

- name: Dispatch to VM or LXC flow
  ansible.builtin.include_tasks: "{{ 'vm.yml' if guest_kind == 'vm' else 'lxc.yml' }}"
```

The `pmx_parse_cephfs` filter isn't a built-in; provide it as a small Ansible filter plugin:

Create `/home/sysop/proxmox-manage/ansible/filter_plugins/pmx_filters.py`:
```python
"""Filter plugins used by pmx roles."""

from __future__ import annotations


def pmx_parse_cephfs(spec: str) -> dict[str, str]:
    """Parse '<subpath>:<guest-path>' into {'subpath': ..., 'dest': ...}.

    >>> pmx_parse_cephfs('supernote:/mnt/sn')
    {'subpath': 'supernote', 'dest': '/mnt/sn'}
    """
    if ":" not in spec:
        raise ValueError(f"cephfs spec must be '<subpath>:<guest-path>', got: {spec!r}")
    subpath, dest = spec.split(":", 1)
    if not subpath.startswith("/"):
        subpath = "/" + subpath
    return {"subpath": subpath, "dest": dest}


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"pmx_parse_cephfs": pmx_parse_cephfs}
```

`tasks/vm.yml` (runs on the VM guest):
```yaml
---
- name: Fail early if workstation-side cephfs.secret is missing
  ansible.builtin.stat:
    path: "{{ ceph_secret_path }}"
  delegate_to: localhost
  become: false
  register: workstation_secret

- name: Fail loudly if missing
  ansible.builtin.fail:
    msg: >-
      pmx requires {{ ceph_secret_path }} on the workstation to copy into VMs.
      Ensure the workstation is already a Ceph client before requesting --cephfs.
  when: not workstation_secret.stat.exists

- name: Install ceph-common (Ubuntu)
  ansible.builtin.apt:
    name: ceph-common
    state: present
  when: guest_os == 'ubuntu'

- name: Enable Ceph repo on Rocky
  ansible.builtin.yum_repository:
    name: ceph
    description: Ceph Reef
    baseurl: https://download.ceph.com/rpm-reef/el9/$basearch
    gpgcheck: true
    gpgkey: https://download.ceph.com/keys/release.asc
    enabled: true
  when: guest_os == 'rocky'

- name: Install ceph-common (Rocky)
  ansible.builtin.dnf:
    name: ceph-common
    state: present
  when: guest_os == 'rocky'

- name: Create /etc/ceph directory
  ansible.builtin.file:
    path: /etc/ceph
    state: directory
    mode: "0755"

- name: Copy ceph.conf from workstation
  ansible.builtin.copy:
    src: "{{ ceph_conf_path }}"
    dest: /etc/ceph/ceph.conf
    owner: root
    group: root
    mode: "0644"

- name: Copy cephfs.secret from workstation (tightened to 0600)
  ansible.builtin.copy:
    src: "{{ ceph_secret_path }}"
    dest: /etc/ceph/cephfs.secret
    owner: root
    group: root
    mode: "0600"

- name: Ensure mount directories exist
  ansible.builtin.file:
    path: "{{ item.dest }}"
    state: directory
    mode: "0755"
  loop: "{{ cephfs_specs }}"

- name: Add fstab entries and mount
  ansible.posix.mount:
    path: "{{ item.dest }}"
    src: "{{ ceph_mons | join(',') }}:6789:{{ item.subpath }}"
    fstype: ceph
    opts: "{{ cephfs_mount_opts }}"
    state: mounted
  loop: "{{ cephfs_specs }}"
```

`tasks/lxc.yml` (runs on the Proxmox node, not the guest):
```yaml
---
- name: Delegate host-side work to the Proxmox node
  block:

    - name: Ensure mount directories exist on host
      ansible.builtin.file:
        path: "/mnt/pmx-passthrough{{ item.subpath }}"
        state: directory
        mode: "0755"
      loop: "{{ cephfs_specs }}"

    - name: Mount CephFS subpaths on the host (if not already)
      ansible.posix.mount:
        path: "/mnt/pmx-passthrough{{ item.subpath }}"
        src: "{{ ceph_mons | join(',') }}:6789:{{ item.subpath }}"
        fstype: ceph
        opts: "{{ cephfs_mount_opts }}"
        state: mounted
      loop: "{{ cephfs_specs }}"

    - name: Find next free mp index for this container
      ansible.builtin.shell: |
        set -e
        for i in $(seq 0 15); do
          if ! grep -q "^mp${i}:" /etc/pve/lxc/{{ guest_vmid }}.conf 2>/dev/null; then
            echo $i; exit 0
          fi
        done
        echo "no free mp slot" >&2; exit 1
      register: mp_index
      changed_when: false

    - name: Append mp line to container config
      ansible.builtin.lineinfile:
        path: "/etc/pve/lxc/{{ guest_vmid }}.conf"
        line: "mp{{ (mp_index.stdout | int) + ansible_loop.index0 }}: /mnt/pmx-passthrough{{ item.subpath }},mp={{ item.dest }},ro=0"
        insertafter: EOF
      loop: "{{ cephfs_specs }}"
      loop_control:
        extended: true

    - name: Restart container so mp lines take effect
      ansible.builtin.shell: |
        pct stop {{ guest_vmid }}
        pct start {{ guest_vmid }}
      changed_when: true

  delegate_to: "{{ target_node }}"
  become: false
```

**Implementation notes:**

- The `vm.yml` path uses `delegate_to: localhost` for the `stat` check so we verify the secret exists on the workstation (where ansible-playbook is running), not inside the brand-new guest.
- The `lxc.yml` path delegates the whole block to the Proxmox node; the configure play's current `hosts: just_created` is the LXC, so delegation is required for host-side `pct` + mount work.
- Restarting the container to apply `mp<N>:` is the standard Proxmox requirement — changes to the LXC config are NOT hot-applied.
- The `mp_index` probe picks the **first free `mp` slot at role-run time** and is consulted once. Subsequent iterations use `ansible_loop.index0` as an offset, so `cephfs_specs` of length *N* consume *N* consecutive slots starting from that first free index. If the container config already has non-contiguous `mp` lines (rare; only if something else has been editing the config), the offsets could collide. For pmx's usage pattern (one tool writes the file) this is safe.

**Verification:**

See Task 5 integration test.

**Commit:** `feat(mount_cephfs): VM-native mount and LXC host-passthrough flow`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: `roles/attach_rbd_disk` — VM-only extra disk

**Verifies:** pmx-provisioning.AC9.1

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/attach_rbd_disk/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/attach_rbd_disk/defaults/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
default_storage: bwrx
rbd_disk_slot: scsi1
```

`tasks/main.yml`:
```yaml
---
- name: Short-circuit if no RBD disk requested
  ansible.builtin.meta: end_host
  when: rbd_disk is none

- name: Attach RBD disk (VM only)
  ansible.builtin.fail:
    msg: "--rbd-disk is VM-only; the CLI should have rejected this combo in Phase 6 Task 1."
  when: guest_kind != 'vm'

- name: Attach RBD-backed disk via qm set
  ansible.builtin.command: >
    qm set {{ guest_vmid }}
    --{{ rbd_disk_slot }} {{ default_storage }}:{{ rbd_disk }}
  delegate_to: "{{ target_node }}"
  changed_when: true
```

**Testing:**

Unit test exists already (Task 1) for the CLI rejection path. The live attach is covered by Task 5 integration test.

**Verification:**

Syntax check (same provision.yml syntax-check command as Phase 3 Task 3 with `rbd_disk=50`).

**Commit:** `feat(attach_rbd_disk): qm set --scsi1 to attach an extra RBD-backed disk`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: `roles/extra_packages` — OS-conditional apt/dnf install

**Verifies:** pmx-provisioning.AC10.1, pmx-provisioning.AC10.2

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/extra_packages/tasks/main.yml`

**Implementation:**

`tasks/main.yml`:
```yaml
---
- name: Short-circuit if no extra packages requested
  ansible.builtin.meta: end_host
  when: extra_packages | default([]) | length == 0

- name: apt install extra packages (Ubuntu)
  ansible.builtin.apt:
    name: "{{ extra_packages }}"
    state: present
    update_cache: true
  when: guest_os == 'ubuntu'
  register: apt_result

- name: dnf install extra packages (Rocky)
  ansible.builtin.dnf:
    name: "{{ extra_packages }}"
    state: present
  when: guest_os == 'rocky'
  register: dnf_result

- name: Surface vmid on package install failure
  ansible.builtin.fail:
    msg: "Package install failed on guest vmid {{ guest_vmid }} ({{ guest_name }}). See previous task output."
  when:
    - (apt_result is failed) or (dnf_result is failed)
```

The `register: ... when: ... is failed` idiom is belt-and-suspenders: Ansible aborts on a failed task by default, but we explicitly produce a message that mentions the vmid so the operator can find the guest in the Proxmox UI.

**Verification:**

Integration test in Task 5.

**Commit:** `feat(extra_packages): conditional apt/dnf install with vmid-annotated failure message`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Wire new roles into `provision.yml`; end-to-end "kitchen sink" integration

**Verifies:** pmx-provisioning.AC8.1, AC8.2, AC8.3, AC9.1, AC10.1, AC11.1, AC11.2

**Files:**
- Modify: `/home/sysop/proxmox-manage/ansible/playbooks/provision.yml`
- Create: `/home/sysop/proxmox-manage/tests/integration/test_kitchen_sink.sh`

**Implementation:**

Configure play becomes:
```yaml
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

    # Phase 8: post_create_hook
```

**Integration test** (`tests/integration/test_kitchen_sink.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD first.}"

NAME="pmxtest-kitchen-$$"

echo "=== Building kitchen-sink VM: ${NAME} ==="
uv run pmx new --name "${NAME}" --kind vm --os ubuntu \
  --cores 2 --memory 2048 --disk 32 \
  --cephfs supernote:/mnt/sn \
  --rbd-disk 10 \
  --extra-packages htop,jq \
  --static-ip 192.168.9.80/24 --static-gw 192.168.9.1

vmid=$(ssh root@192.168.9.12 "qm list | awk -v n=${NAME} '\$2==n{print \$1}'")
echo "VMID: ${vmid}"

# Verify extra disk attached (AC9.1)
ssh root@192.168.9.12 "qm config ${vmid} | grep -E '^scsi1:\s+bwrx:.+,size=10G'"

# Verify static IP (AC11.1)
ssh -o StrictHostKeyChecking=accept-new ansible@192.168.9.80 \
  "ip -4 addr show | grep -q 'inet 192.168.9.80/24'"

# Verify cephfs mount (AC8.1)
ssh ansible@192.168.9.80 "findmnt /mnt/sn | grep -q ceph"

# Verify extra packages (AC10.1)
ssh ansible@192.168.9.80 "which htop && which jq"

# Cleanup
ssh root@192.168.9.12 "qm stop ${vmid} && qm destroy ${vmid} --purge"

echo "=== Kitchen-sink VM passed all checks ==="

# Now the LXC variant (no --rbd-disk; LXC rejection was covered in Task 1 unit test).
LXC_NAME="pmxtest-kitchen-lxc-$$"

echo "=== Building kitchen-sink LXC: ${LXC_NAME} (NOTE: --static-gw deliberately omitted — exercises the .1-of-subnet inference path) ==="
uv run pmx new --name "${LXC_NAME}" --kind lxc --os rocky \
  --cores 1 --memory 1024 --disk 8 \
  --cephfs supernote:/mnt/sn \
  --extra-packages htop,jq \
  --static-ip 192.168.9.81/24

lxc_vmid=$(ssh root@192.168.9.12 "pct list | awk -v n=${LXC_NAME} '\$NF==n{print \$1}'")
echo "LXC VMID: ${lxc_vmid}"

# Verify LXC mp line exists (AC8.2, AC2.3)
ssh root@192.168.9.12 "grep -E '^mp[0-9]+:.*mp=/mnt/sn' /etc/pve/lxc/${lxc_vmid}.conf"

# Verify mount is visible inside container
ssh root@192.168.9.12 "pct exec ${lxc_vmid} -- findmnt /mnt/sn | grep -q /mnt/sn"

# Verify static IP on LXC (AC11.2)
ssh -o StrictHostKeyChecking=accept-new root@192.168.9.81 \
  "ip -4 addr show | grep -q 'inet 192.168.9.81/24'"

# Verify inferred gateway picked up the .1-of-subnet default (AC11.2, Critical 2 regression guard)
ssh root@192.168.9.81 "ip -4 route show default | grep -q '192.168.9.1'"

# Verify extra packages (AC10.1 on Rocky via dnf)
ssh root@192.168.9.81 "which htop && which jq"

# Cleanup
ssh root@192.168.9.12 "pct stop ${lxc_vmid} && pct destroy ${lxc_vmid} --purge"

echo "=== Kitchen-sink LXC passed all checks ==="
```

**Verification:**

```bash
chmod +x tests/integration/test_kitchen_sink.sh
./tests/integration/test_kitchen_sink.sh
```
Expected: both guests built, all checks pass, both destroyed.

**Commit:** `feat(provision): wire mount_cephfs, attach_rbd_disk, extra_packages into configure play`
<!-- END_TASK_5 -->

---

## Phase 6 done when

- `pmx new ... --cephfs supernote:/mnt/sn ... --kind vm` results in a VM with `ceph-common` installed, fstab entry present, live mount surviving reboot (AC8.1)
- Same invocation with `--kind lxc` results in a host-side mount + `mp<N>:` pass-through line; no `ceph-common` inside the container (AC8.2, AC2.3)
- Re-running against an existing `/mnt/pmx-passthrough/<subpath>` host mount does not duplicate or remount (AC8.3)
- Missing `/etc/ceph/cephfs.secret` on the workstation fails the VM path with a clear "ensure workstation is a Ceph client" message (AC8.4)
- `--rbd-disk 10` attaches a 10G RBD disk at `scsi1` on VMs (AC9.1); rejected by CLI unit test when combined with `--kind lxc` (AC9.2)
- `--extra-packages htop,jq` installs htop and jq on both Ubuntu (apt) and Rocky (dnf) (AC10.1); unknown package name fails with vmid annotation (AC10.2)
- `--static-ip 192.168.9.80/24` without `--static-gw` boots VM and LXC with the requested IP and an inferred gateway of `192.168.9.1` (AC11.1, AC11.2); absence of the flag keeps DHCP (AC11.3)
- `tests/unit/test_cli.py::test_rbd_disk_rejects_lxc` passes under pytest
- `tests/integration/test_kitchen_sink.sh` passes against the real cluster
- Clean `git status` after commits from Tasks 1–5
