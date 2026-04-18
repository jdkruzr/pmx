# pmx Provisioning — Phase 4: LXC Creation Path with UID-Map Fix

**Goal:** `pmx new --kind lxc --os {ubuntu|rocky} --no-domain` produces a running, SSH-reachable **unprivileged** LXC with the UID/GID map extended to cover SSSD's high UIDs (~5×10⁸). The configure phase runs the `common` role; domain join lands in Phase 5.

**Architecture:** `pmx new --kind lxc` triggers `provision.yml`'s create play to include `create_lxc` instead of `create_vm`. The role: (1) picks the latest cached LXC template for the requested OS, (2) allocates a new VMID, (3) ensures `/etc/subuid` + `/etc/subgid` contain the 1B-slot mapping `root:100000:1000000000` on the Proxmox host, (4) runs `pct create` with `unprivileged=1`, `features=nesting=1,keyctl=1`, (5) injects the `lxc.idmap` block into `/etc/pve/lxc/<vmid>.conf` **before starting the container**, (6) starts the container, (7) waits for SSH, (8) `add_host`s into `just_created`.

**Tech Stack:** `community.proxmox.proxmox` for LXC lifecycle (where it helps) or raw `pct`; `ansible.builtin.blockinfile` for `subuid`/`subgid`/`<vmid>.conf` edits.

**Scope:** Phase 4 of 8.

**Codebase verified:** 2026-04-18. Phase 1–3 artifacts in place. `ansible/roles/create_vm/`, `ansible/roles/common/` exist. `ansible/playbooks/provision.yml`'s create play has one `include_role: create_vm` under `when: guest_kind == "vm"`. Rocky LXC template from Phase 2 cached on `cephfs`. Ubuntu LXC templates already cached on the Proxmox host (24.04 is present per cluster inspection).

**External dependency investigation findings:**
- ✓ **UID-map recipe** (research-verified, differs from design's first draft): SSSD generates UIDs in the ~5×10⁸ range; the minimal working mapping for an unprivileged LXC that needs to resolve domain users is:
  ```
  lxc.idmap = u 0 100000 65536
  lxc.idmap = g 0 100000 65536
  lxc.idmap = u 500000000 500000000 99999999
  lxc.idmap = g 500000000 500000000 99999999
  ```
  The second pair maps SSSD's high-UID range directly into the container. Total of ~1 billion UID slots; hosts `/etc/subuid` and `/etc/subgid` must contain a matching single-line allocation for root: `root:100000:1000000000`.
- ✓ **Feature flags are set-at-create-time only.** `pct set <vmid> --features ...` does NOT update post-creation; container must be destroyed and recreated. So we MUST pass `--unprivileged 1 --features nesting=1,keyctl=1` at creation.
- ✓ `community.proxmox.proxmox` (LXC module) supports `unprivileged`, `features`, `cores`, `memory`, `rootfs`, `netif`, `ostemplate`, `hostname`, `pubkey`, `storage`. Pattern for LXC feature flags: pass as a mapping (`features: nesting=1,keyctl=1`) or comma string depending on collection version — 1.6.x accepts comma string.
- ✓ LXC doesn't run qemu-guest-agent (it's a container). IP discovery is via `pct exec <vmid> -- ip -j addr show` OR via the `ansible` user we pre-install in the template's authorized_keys via `--ssh-public-keys` on `pct create`.
- 📖 Sources: [Proxmox forum: can't log in to lxc containers w/ AD creds](https://forum.proxmox.com/threads/cant-log-in-to-lxc-containers-w-ad-creds-after-joining-to-ad.58752/), [Proxmox wiki: Unprivileged LXC containers](https://pve.proxmox.com/wiki/Unprivileged_LXC_containers), [community.proxmox LXC module](https://docs.ansible.com/projects/ansible/latest/collections/community/proxmox/proxmox_module.html).

---

## Acceptance Criteria Coverage

### pmx-provisioning.AC2: Unprivileged LXC with UID-map fix
- **pmx-provisioning.AC2.1 Success:** LXC created as unprivileged; `cat /proc/self/uid_map` inside shows extended range covering SSSD's ~5e8 UIDs
- **pmx-provisioning.AC2.4 Failure:** If idmap write to `/etc/pve/lxc/<vmid>.conf` fails, creation bails before start

*(AC2.2 and AC2.3 depend on Phase 5's domain join and Phase 6's Ceph pass-through; they get verified in those phases.)*

### pmx-provisioning.AC4: Ubuntu and Rocky both first-class
- **pmx-provisioning.AC4.1 Success (LXC variant):** `--os ubuntu --kind lxc` builds a working Ubuntu 24.04 LXC
- **pmx-provisioning.AC4.2 Success (LXC variant):** `--os rocky --kind lxc` builds a working Rocky 9 LXC

---

<!-- START_TASK_1 -->
### Task 1: Remove LXC stub from CLI; extend provision.yml create play

**Verifies:** pmx-provisioning.AC2.1, pmx-provisioning.AC4.1, pmx-provisioning.AC4.2 (wiring)

**Files:**
- Modify: `/home/sysop/proxmox-manage/pmx/cli.py` — remove the `if kwargs["kind"] == "lxc": ... sys.exit(NOT_IMPLEMENTED_EXIT)` block added in Phase 3 Task 1
- Modify: `/home/sysop/proxmox-manage/ansible/playbooks/provision.yml` — uncomment/add the `include_role: create_lxc` block in the create play

**Implementation:**

`pmx/cli.py` — delete these three lines from `cmd_new`:
```python
    if kwargs["kind"] == "lxc":
        click.echo("pmx new --kind lxc not yet implemented (Phase 4).", err=True)
        sys.exit(NOT_IMPLEMENTED_EXIT)
```

`ansible/playbooks/provision.yml` — the create play becomes:
```yaml
- name: Create guest on Proxmox
  hosts: "{{ target_node }}"
  gather_facts: false
  become: false
  tasks:
    - name: Create VM
      ansible.builtin.include_role:
        name: create_vm
      when: guest_kind == "vm"

    - name: Create LXC
      ansible.builtin.include_role:
        name: create_lxc
      when: guest_kind == "lxc"
```

**Verification:**

```bash
cd /home/sysop/proxmox-manage
uv run pmx new --name x --kind lxc --os ubuntu --no-domain --dry-run
```
Expected: prints the ansible-playbook command that *would* run, exit 0. (Real invocation would fail with "role 'create_lxc' not found" — that's Task 2.)

**Commit:** `feat(cli): remove lxc stub; wire lxc kind through provision.yml`
<!-- END_TASK_1 -->

<!-- START_SUBCOMPONENT_A (tasks 2-4) -->
<!-- START_TASK_2 -->
### Task 2: `roles/create_lxc` — host-side subuid/subgid preparation

**Verifies:** pmx-provisioning.AC2.1

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/create_lxc/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/create_lxc/tasks/subuid.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/create_lxc/defaults/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
default_lxc_storage: cephfs
default_bridge: vmbr0
ssh_wait_timeout: 180

# UID-map recipe for SSSD-compatible unprivileged LXCs. ~1 billion UID slots.
# See: Proxmox forum thread on AD-joined unprivileged LXCs.
subuid_entry: "root:100000:1000000000"
lxc_idmap_block: |
  lxc.idmap = u 0 100000 65536
  lxc.idmap = g 0 100000 65536
  lxc.idmap = u 500000000 500000000 99999999
  lxc.idmap = g 500000000 500000000 99999999
```

`tasks/subuid.yml` (host-side prep; idempotent):
```yaml
---
# Ensure /etc/subuid and /etc/subgid contain the 1B-slot allocation for root.
# We use a marker line so we can safely re-run and so manually-added entries
# (e.g. for other LXC users) are not clobbered.

- name: Ensure /etc/subuid has pmx allocation
  ansible.builtin.blockinfile:
    path: /etc/subuid
    marker: "# {mark} pmx uid allocation"
    block: "{{ subuid_entry }}"
    create: true
    mode: "0644"

- name: Ensure /etc/subgid has pmx allocation
  ansible.builtin.blockinfile:
    path: /etc/subgid
    marker: "# {mark} pmx gid allocation"
    block: "{{ subuid_entry }}"
    create: true
    mode: "0644"
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

- name: Ensure host subuid/subgid are prepared
  ansible.builtin.include_tasks: subuid.yml

- name: Discover the latest LXC template for requested OS
  ansible.builtin.shell: |
    set -eo pipefail
    pveam list {{ default_lxc_storage }} \
      | awk '{print $1}' \
      | grep -E '{{ lxc_template_pattern[guest_os] }}' \
      | sort \
      | tail -1
  vars:
    lxc_template_pattern:
      ubuntu: 'ubuntu-(24|25)\.[0-9]+-standard'
      rocky: 'rockylinux-9-default'
  register: lxc_template_probe
  changed_when: false

- name: Fail if no matching template is cached
  ansible.builtin.fail:
    msg: >-
      No LXC template matching {{ guest_os }} found on {{ default_lxc_storage }}.
      Run `pmx seed` first.
  when: lxc_template_probe.stdout | trim | length == 0

- name: Set template_ref fact
  ansible.builtin.set_fact:
    template_ref: "{{ lxc_template_probe.stdout | trim }}"

- name: Read operator SSH pubkey for container authorized_keys
  ansible.builtin.set_fact:
    ci_ssh_pubkey: "{{ lookup('file', lookup('env', 'HOME') + '/.ssh/id_ed25519.pub', errors='ignore') | default('', true) }}"

- name: Fail if no SSH pubkey available on the Proxmox host
  ansible.builtin.fail:
    msg: "root's ~/.ssh/id_ed25519.pub not found on {{ target_node }}; populate it before running."
  when: ci_ssh_pubkey | length == 0

- name: Render authorized_keys to a temp file (pct consumes a file path)
  ansible.builtin.copy:
    content: "{{ ci_ssh_pubkey }}\n"
    dest: "/tmp/pmx-{{ new_vmid }}.pub"
    mode: "0600"

- name: Compute effective static gateway (inferred as .1 of the subnet unless --static-gw supplied)
  ansible.builtin.set_fact:
    effective_static_gw: >-
      {{ static_gw
         if (static_gw | default('', true) | length > 0)
         else (static_ip | ansible.utils.ipaddr('network') | ansible.utils.ipmath(1)) }}
  when: static_ip is not none

- name: Create unprivileged LXC with required features
  ansible.builtin.command: >
    pct create {{ new_vmid }}
    {{ default_lxc_storage }}:vztmpl/{{ template_ref }}
    --hostname {{ guest_name }}
    --cores {{ cores }}
    --memory {{ memory }}
    --rootfs {{ default_lxc_storage }}:{{ disk }}
    --net0 name=eth0,bridge={{ default_bridge }},firewall=0,ip={{ 'dhcp' if not static_ip else (static_ip + ',gw=' + effective_static_gw) }}
    --unprivileged 1
    --features nesting=1,keyctl=1
    --ssh-public-keys /tmp/pmx-{{ new_vmid }}.pub
    --onboot 0
    {{ '--searchdomain ' + ad_domain if domain_join | bool else '' }}
  changed_when: true

- name: Clean up temp pubkey file
  ansible.builtin.file:
    path: "/tmp/pmx-{{ new_vmid }}.pub"
    state: absent

- name: Write extended idmap block into the container config (pre-start)
  ansible.builtin.blockinfile:
    path: "/etc/pve/lxc/{{ new_vmid }}.conf"
    marker: "# {mark} pmx idmap"
    block: "{{ lxc_idmap_block }}"
    state: present

- name: Start the container
  ansible.builtin.command: "pct start {{ new_vmid }}"
  changed_when: true

- name: Wait for network inside the container
  ansible.builtin.shell: |
    set -e
    for i in $(seq 1 30); do
      out=$(pct exec {{ new_vmid }} -- ip -j addr show 2>/dev/null || true)
      if [ -n "$out" ] && echo "$out" | python3 -c 'import json,sys; ifs=json.load(sys.stdin); [a for i in ifs if i["ifname"]!="lo" for a in i.get("addr_info",[]) if a["family"]=="inet" and not a["local"].startswith("127.")][0]'; then
        exit 0
      fi
      sleep 3
    done
    exit 1
  changed_when: false

- name: Discover container IPv4
  ansible.builtin.command: "pct exec {{ new_vmid }} -- ip -j addr show"
  register: ip_raw
  changed_when: false

- name: Parse IPv4 from inside the container
  ansible.builtin.set_fact:
    guest_ip: >-
      {{ (ip_raw.stdout | from_json
          | rejectattr('ifname', 'eq', 'lo')
          | map(attribute='addr_info') | flatten
          | selectattr('family', 'eq', 'inet')
          | rejectattr('local', 'search', '^127\\.')
          | map(attribute='local') | first) | default(none) }}

- name: Discover container MAC (for state log in Phase 8)
  ansible.builtin.command: "pct config {{ new_vmid }}"
  register: pct_config
  changed_when: false

- name: Parse MAC from pct config net0
  ansible.builtin.set_fact:
    guest_mac: "{{ pct_config.stdout | regex_search('net0:.*hwaddr=([0-9A-Fa-f:]+)', '\\1') | first | default('') }}"

- name: Fail if IPv4 not discovered
  ansible.builtin.fail:
    msg: "Container {{ guest_name }} (VMID {{ new_vmid }}) did not acquire an IPv4 address within the timeout."
  when: guest_ip is none or guest_ip == ""

- name: Add container to in-memory inventory as `just_created`
  ansible.builtin.add_host:
    name: "{{ guest_name }}"
    ansible_host: "{{ guest_ip }}"
    ansible_user: root
    ansible_ssh_common_args: "-o StrictHostKeyChecking=accept-new"
    groups: just_created
    guest_vmid: "{{ new_vmid }}"
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

- name: Show discovered IP for operator
  ansible.builtin.debug:
    msg: "LXC {{ guest_name }} (vmid {{ new_vmid }}) reachable at {{ guest_ip }}."
```

**Implementation notes:**

- LXC root login uses `root@<ip>`, not `ansible@<ip>` (pct `--ssh-public-keys` populates root's authorized_keys on Proxmox-provided templates). The common role runs as root inside LXCs (no sudo needed).
- We set `firewall=0` explicitly because the Proxmox default can block outbound DHCP on some clusters; adjust if your site policy differs.
- The `--rootfs {{ default_lxc_storage }}:{{ disk }}` syntax allocates disk size on the chosen storage. Cephfs supports subvolume-style LXC rootfs.
- `blockinfile` with a distinct marker (`# BEGIN pmx idmap`...`# END pmx idmap`) is safe against re-runs and won't clobber any other lines added manually.

**Testing:**

Role-level molecule test is out of scope (LXC testing under molecule requires a Proxmox-shaped environment). Use Task 4's integration test instead.

**Verification:**

Syntax check:
```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=lxc -e guest_os=ubuntu -e guest_name=x \
  -e cores=2 -e memory=1024 -e disk=8 -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e domain_join=false \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12
```
Expected: syntax OK.

**Commit:** `feat(create_lxc): unprivileged LXC with extended UID map + subuid/subgid prep`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Ensure `common` role runs correctly against LXCs (become, systemd quirks)

**Verifies:** pmx-provisioning.AC4.1, pmx-provisioning.AC4.2 (LXC variants)

**Files:**
- Modify: `/home/sysop/proxmox-manage/ansible/playbooks/provision.yml`
- Modify: `/home/sysop/proxmox-manage/ansible/roles/common/tasks/main.yml`

**Implementation:**

LXCs don't need `qemu-guest-agent`, and they're often connected as root so `become: true` is redundant. Guard the guest-agent tasks with `when: guest_kind == "vm"`.

Edit `ansible/roles/common/tasks/ubuntu.yml` — guard the last two tasks (install qemu-guest-agent + enable service):
```yaml
- name: Install base packages
  ansible.builtin.apt:
    name: >-
      {{ common_base_packages_ubuntu
         | reject('equalto','qemu-guest-agent')
         | list if guest_kind == 'lxc'
         else common_base_packages_ubuntu }}
    state: present

- name: Enable and start qemu-guest-agent
  ansible.builtin.systemd:
    name: qemu-guest-agent
    state: started
    enabled: true
  when: guest_kind == "vm"
```

Do the same for `rocky.yml`.

In `ansible/playbooks/provision.yml`, configure play: make `become: true` conditional so LXC-as-root doesn't attempt sudo-to-self:
```yaml
- name: Configure guest
  hosts: just_created
  gather_facts: true
  become: "{{ guest_kind == 'vm' }}"
  tasks:
    - name: Run common bootstrap (upgrade + base packages)
      ansible.builtin.include_role:
        name: common
```

**Testing:**

Covered by Task 4's integration test (runs `common` against both a VM and an LXC).

**Verification:**

Syntax check again (same command as Task 2's Verification).
Expected: syntax OK.

**Commit:** `feat(common): guard qemu-guest-agent for LXC; conditional become in provision.yml`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: End-to-end LXC integration test (Ubuntu and Rocky)

**Verifies:** pmx-provisioning.AC2.1, pmx-provisioning.AC4.1 (LXC), pmx-provisioning.AC4.2 (LXC)

**Files:**
- Create: `/home/sysop/proxmox-manage/tests/integration/test_create_lxc.sh`

**Implementation:**

```bash
#!/usr/bin/env bash
set -euo pipefail

# tests/integration/test_create_lxc.sh — exercises pmx new --kind lxc end-to-end.
# Requires: pmx seed already run (Rocky LXC template present on cephfs).

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

smoke_test() {
  local os="$1"
  local name="pmxtest-lxc-${os}-$$"

  echo "=== Building ${os} LXC named ${name} ==="
  AD_JOIN_PASSWORD=x uv run pmx new \
    --name "${name}" \
    --kind lxc \
    --os "${os}" \
    --cores 1 --memory 1024 --disk 8 \
    --no-domain

  local vmid
  vmid=$(ssh root@192.168.9.12 "pct list | awk -v n=${name} '\$NF==n{print \$1}'")
  if [ -z "${vmid}" ]; then echo "VMID not found for ${name}"; exit 1; fi
  echo "VMID: ${vmid}"

  echo "=== Checking unprivileged-with-idmap ==="
  ssh root@192.168.9.12 "grep -c '^unprivileged: 1' /etc/pve/lxc/${vmid}.conf"  # expects 1
  ssh root@192.168.9.12 "grep -c '^lxc.idmap = u 500000000' /etc/pve/lxc/${vmid}.conf"  # expects 1
  ssh root@192.168.9.12 "pct exec ${vmid} -- cat /proc/self/uid_map" \
    | tee /dev/stderr \
    | grep -q "500000000 500000000 99999999"

  echo "=== Checking SSH reachability from workstation ==="
  local ip
  ip=$(ssh root@192.168.9.12 "pct exec ${vmid} -- ip -j addr show" \
        | python3 -c 'import json,sys; print([a["local"] for i in json.load(sys.stdin) if i["ifname"]!="lo" for a in i.get("addr_info",[]) if a["family"]=="inet" and not a["local"].startswith("127.")][0])')
  ssh -o StrictHostKeyChecking=accept-new root@${ip} "which tmux && which curl && which python3"

  echo "=== ${name} OK ==="
}

smoke_test ubuntu
smoke_test rocky
echo "Both LXC OS families passed."
```

**Verification:**

```bash
chmod +x tests/integration/test_create_lxc.sh
./tests/integration/test_create_lxc.sh
```
Expected: Both LXCs created, `/proc/self/uid_map` inside each shows the `500000000 500000000 99999999` line (AC2.1 verified), SSH as root works, base tools installed.

**Failure-path verification for AC2.4:**

```bash
# Simulate an idmap-write failure by making the pve config dir read-only for a moment.
# (Or edit lxc_idmap_block to an obviously invalid syntax in a branch and observe pct start fails clearly.)
# This is a manual verification; treat as optional documentation rather than a CI hook.
```

Cleanup:
```bash
ssh root@192.168.9.12 "for n in pmxtest-lxc-*; do vmid=\$(pct list | awk -v n=\$n '\$NF==n{print \$1}'); [ -n \"\$vmid\" ] && pct stop \$vmid; [ -n \"\$vmid\" ] && pct destroy \$vmid --purge; done"
```

**Commit:** `test(create_lxc): integration harness for Ubuntu + Rocky LXC + UID-map check`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_A -->

---

## Phase 4 done when

- `pmx new --name foo --kind lxc --os ubuntu --no-domain` produces a running unprivileged Ubuntu 24.04 LXC, SSH-reachable as `root@<ip>`, with base packages installed (AC2.1, AC4.1)
- Same with `--os rocky` produces an unprivileged Rocky 9 LXC (AC2.1, AC4.2)
- `cat /proc/self/uid_map` inside the LXC shows the `500000000 500000000 99999999` line (AC2.1)
- `/etc/subuid` and `/etc/subgid` on the host contain a marker-wrapped `root:100000:1000000000` line; re-running `pmx new` does not duplicate or alter the block
- Syntax-check passes for `provision.yml` with full LXC extra-vars
- Integration test `tests/integration/test_create_lxc.sh` passes against the real cluster
- Clean `git status` after commits from Tasks 1–4
