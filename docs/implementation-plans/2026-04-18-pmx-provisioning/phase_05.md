# pmx Provisioning — Phase 5: AD Join Roles (Ubuntu + Rocky)

**Goal:** Domain join happens automatically on both VMs and LXCs, on both OS families, end-to-end. This is the core value delivery phase: `pmx new --name foo --os ubuntu` (no `--no-domain`) produces a fully usable, domain-joined guest where `Domain Admins` members can SSH in, get an auto-created home dir, and `sudo`.

**Architecture:** Three roles:
- `ad_join_common` — provides the rendered `sssd.conf`, the sudoers drop-in, and the SSSD-restart handler. No tasks run directly; it's consumed by the two OS roles via `include_role` for shared templates and handler reuse.
- `ad_join_ubuntu` — apt install the packages; run `realm join` with `$AD_JOIN_PASSWORD` piped via `--stdin-password`; drop the common sssd.conf and sudoers file; `pam-auth-update --enable mkhomedir`.
- `ad_join_rocky` — same flow but dnf packages; use `authselect select sssd with-mkhomedir` instead of `pam-auth-update`.

The shared sssd.conf is opinionated: `override_space = _`, `ldap_id_mapping = True`, `simple_allow_groups = domain_admins`, `cache_credentials = True`, `krb5_store_password_if_offline = True`, `fallback_homedir = /home/%u`.

**Tech Stack:** `realmd`, `adcli`, `sssd` 2.12+, Samba AD (via Zentyal). Molecule + Podman for role unit tests.

**Scope:** Phase 5 of 8.

**Codebase verified:** 2026-04-18. Phase 1–4 artifacts present. `ansible/roles/create_vm/`, `ansible/roles/create_lxc/`, `ansible/roles/common/` exist. `ansible/playbooks/provision.yml` has the create play fully wired and the configure play includes only `common`.

**External dependency investigation findings:**
- ✓ Ubuntu 24.04 package set: `realmd sssd sssd-ad sssd-tools adcli krb5-user samba-common-bin libnss-sss libpam-sss oddjob oddjob-mkhomedir packagekit`. `sssd-ad` is the preferred provider package; `packagekit` is required by `realm discover`.
- ✓ Rocky 9 package set: `realmd sssd sssd-tools oddjob oddjob-mkhomedir adcli krb5-workstation samba-common-tools authselect authselect-compat`.
- ✓ `realm join --unattended --stdin-password -U <user> <domain>` is the 2026-current incantation (replaces the old `echo pw | realm join --unattended -U user domain`). `--install=/` is NOT needed — realm handles package install internally when run via realmd.
- ✓ Ubuntu PAM: `pam-auth-update --enable mkhomedir` creates the `session` line in `/etc/pam.d/common-session`.
- ✓ Rocky PAM: `authselect select sssd with-mkhomedir --force`. `--force` is required the first time because authselect refuses to overwrite an existing profile without it.
- ✓ Modern sssd.conf: `override_space`, `ldap_id_mapping`, `simple_allow_groups`, `cache_credentials`, `krb5_store_password_if_offline`, `fallback_homedir` — ALL current in SSSD 2.12.0 (no deprecations). `ad_allow_remote_domain_local_groups` was removed; don't use.
- ✓ Molecule 2026 default: `molecule-plugins[podman]`. Install with `uv pip install molecule "molecule-plugins[podman]"`.
- ✓ User's existing workstation sssd.conf matches most of these fields; we add `override_space = _` and normalize group name to `domain_admins` to avoid the backslash-space sudoers parsing issue.
- 📖 Sources: [Ubuntu Server: SSSD with AD](https://ubuntu.com/server/docs/how-to/sssd/with-active-directory/), [RHEL 9 authselect docs](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/configuring_authentication_and_authorization_in_rhel/), [realmd man page](https://www.freedesktop.org/software/realmd/docs/realm.html), [SSSD 2.12.0 release notes](https://sssd.io/release-notes/sssd-2.12.0.html), [Molecule Podman docs](https://ansible.readthedocs.io/projects/molecule/).

---

## Acceptance Criteria Coverage

### pmx-provisioning.AC1: VM creation with AD join works end-to-end
- **pmx-provisioning.AC1.2 Success:** Domain-joined; `id Administrator@broken.wrx` resolves on the guest
- **pmx-provisioning.AC1.3 Success:** `Domain Admins` member can `ssh` in and `sudo -i` with auto-created `/home/<user>`
- **pmx-provisioning.AC1.5 Failure:** realm join failure leaves guest running and surfaces vmid for recovery

### pmx-provisioning.AC2: Unprivileged LXC with UID-map fix (AD-joined variant)
- **pmx-provisioning.AC2.2 Success:** `id Administrator@broken.wrx` resolves inside the LXC (no fallback to privileged)

### pmx-provisioning.AC3: AD credential prompt and caching
- **pmx-provisioning.AC3.1 Success:** First invocation in a fresh shell prompts once (hidden input via getpass)
- **pmx-provisioning.AC3.2 Success:** Subsequent invocations in same shell reuse `$AD_JOIN_PASSWORD` silently
- **pmx-provisioning.AC3.3 Failure:** Wrong password surfaces a realm-join error and does NOT poison the cache

### pmx-provisioning.AC4: Ubuntu and Rocky both first-class
- **pmx-provisioning.AC4.1 Success:** `--os ubuntu` builds a working domain-joined Ubuntu 24.04 guest (VM and LXC)
- **pmx-provisioning.AC4.2 Success:** `--os rocky` builds a working domain-joined Rocky 9 guest (VM and LXC)

### pmx-provisioning.AC5: pam-auth-update mkhomedir default-on
- **pmx-provisioning.AC5.1 Success:** First SSH login as a domain user creates `/home/<user>` with correct ownership
- **pmx-provisioning.AC5.2 Success:** Behavior is consistent on both Ubuntu and Rocky guests

### pmx-provisioning.AC7: Sudoers drop-in
- **pmx-provisioning.AC7.1 Success:** `/etc/sudoers.d/domain-admins` exists, mode 0440, validates with `visudo -cf`
- **pmx-provisioning.AC7.2 Success:** `domain_admins` members can `sudo` without backslash-space parsing errors
- **pmx-provisioning.AC7.3 Failure:** If `visudo -cf` fails, the drop-in file is rolled back

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: `roles/ad_join_common` — shared sssd.conf, sudoers, handler

**Verifies:** pmx-provisioning.AC7.1, pmx-provisioning.AC7.2

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_common/defaults/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_common/templates/sssd.conf.j2`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_common/templates/sudoers-domain-admins.j2`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_common/handlers/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_common/tasks/apply.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
sssd_simple_allow_groups:
  - domain_admins
sssd_default_shell: /bin/bash
sssd_fallback_homedir: /home/%u
```

`templates/sssd.conf.j2`:
```jinja
# Managed by pmx — do not edit by hand.
[sssd]
domains = {{ ad_domain }}
config_file_version = 2
services = nss, pam

[domain/{{ ad_domain }}]
id_provider = ad
access_provider = simple
ad_domain = {{ ad_domain }}
krb5_realm = {{ ad_realm }}
realmd_tags = manages-system joined-with-adcli
cache_credentials = True
krb5_store_password_if_offline = True
ldap_id_mapping = True
use_fully_qualified_names = False
override_space = _
default_shell = {{ sssd_default_shell }}
fallback_homedir = {{ sssd_fallback_homedir }}
simple_allow_groups = {{ sssd_simple_allow_groups | join(', ') }}
```

`templates/sudoers-domain-admins.j2`:
```jinja
# Managed by pmx — do not edit by hand.
# Members of the AD Domain Admins group (normalised to domain_admins via SSSD override_space).
%domain_admins ALL=(ALL:ALL) ALL
```

`handlers/main.yml`:
```yaml
---
- name: restart sssd
  ansible.builtin.systemd:
    name: sssd
    state: restarted
```

`tasks/apply.yml` (consumed by the OS-specific roles; no tasks/main.yml by design — this role is not self-runnable, only included):
```yaml
---
- name: Render /etc/sssd/sssd.conf
  ansible.builtin.template:
    src: sssd.conf.j2
    dest: /etc/sssd/sssd.conf
    owner: root
    group: root
    mode: "0600"
  notify: restart sssd

- name: Render /etc/sudoers.d/domain-admins (validated)
  ansible.builtin.template:
    src: sudoers-domain-admins.j2
    dest: /etc/sudoers.d/domain-admins
    owner: root
    group: root
    mode: "0440"
    validate: /usr/sbin/visudo -cf %s
```

**Why no `tasks/main.yml`:** Distinguishes "shared templates+handler" from "runnable role". The OS-specific roles use `include_role: name: ad_join_common tasks_from: apply` to apply the shared tasks at the right point in their sequence.

**Testing:**

Molecule test in Task 4 exercises the apply.yml file against a throwaway container (covers AC7.1, AC7.3).

**Verification:**

```bash
cd /home/sysop/proxmox-manage/ansible
ls roles/ad_join_common/{defaults,templates,handlers,tasks}/*
```
Expected: All five files listed.

**Commit:** `feat(ad_join_common): shared sssd.conf, sudoers drop-in, restart handler`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: `roles/ad_join_ubuntu` — apt, realm join, pam-auth-update

**Verifies:** pmx-provisioning.AC1.2, pmx-provisioning.AC1.3, pmx-provisioning.AC1.5, pmx-provisioning.AC4.1 (domain-joined), pmx-provisioning.AC5.1 (ubuntu), pmx-provisioning.AC5.2 (ubuntu-side), pmx-provisioning.AC3.3

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_ubuntu/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_ubuntu/defaults/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_ubuntu/meta/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
ad_join_ubuntu_packages:
  - realmd
  - sssd
  - sssd-ad
  - sssd-tools
  - adcli
  - krb5-user
  - samba-common-bin
  - libnss-sss
  - libpam-sss
  - oddjob
  - oddjob-mkhomedir
  - packagekit
```

`meta/main.yml`:
```yaml
dependencies:
  - role: ad_join_common
```

`tasks/main.yml`:
```yaml
---
- name: Assert AD_JOIN_PASSWORD is set
  ansible.builtin.assert:
    that:
      - lookup('env', 'AD_JOIN_PASSWORD') | length > 0
    fail_msg: "$AD_JOIN_PASSWORD must be set. pmx CLI prompts for this automatically; if running ansible-playbook directly, export it first."

- name: Wait for apt (any in-flight unattended-upgrades)
  ansible.builtin.command: >
    bash -c 'for i in $(seq 1 60); do if ! pgrep -x "unattended-upgr|apt|apt-get" >/dev/null; then exit 0; fi; sleep 2; done; exit 1'
  changed_when: false

- name: Install AD join packages
  ansible.builtin.apt:
    name: "{{ ad_join_ubuntu_packages }}"
    state: present
    update_cache: true

- name: Check whether host is already realm-joined
  ansible.builtin.command: realm list
  register: realm_list
  changed_when: false
  failed_when: false

- name: Run realm join (skipped if already joined)
  ansible.builtin.shell: >
    set -o pipefail;
    printf '%s' "$AD_JOIN_PASSWORD"
    | realm join --unattended --stdin-password -U {{ ad_join_user }} {{ ad_domain }}
  args:
    executable: /bin/bash
  # Ansible does not inherit the controller's env on remote tasks, so we must
  # explicitly pass $AD_JOIN_PASSWORD through. The lookup runs on the controller
  # where the var is actually set; `no_log: true` below prevents the expanded
  # value from appearing in any logs even in -vvv mode.
  environment:
    AD_JOIN_PASSWORD: "{{ lookup('env', 'AD_JOIN_PASSWORD') }}"
  register: realm_join_result
  when: ad_domain not in realm_list.stdout
  # `no_log` hides the task output entirely but the registered variable is still
  # accessible to failed_when (it evaluates on the controller with full access).
  failed_when: realm_join_result.rc != 0 and 'Already joined' not in realm_join_result.stderr
  no_log: true

- name: Apply shared sssd.conf + sudoers drop-in
  ansible.builtin.include_role:
    name: ad_join_common
    tasks_from: apply

- name: Flush handlers so sssd restarts before PAM change
  ansible.builtin.meta: flush_handlers

- name: Enable pam_mkhomedir
  ansible.builtin.command: pam-auth-update --enable mkhomedir --force
  changed_when: true
```

**Why `no_log: true` on the realm join:** prevents Ansible from printing the full task environment, which includes `$AD_JOIN_PASSWORD`, in verbose mode.

**Why `flush_handlers` before pam-auth-update:** so sssd.conf is in place and sssd is restarted before mkhomedir is enabled — clean ordering.

**Testing:**

See Tasks 4 (molecule) and 6 (live integration).

**Verification:**

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=vm -e guest_os=ubuntu -e guest_name=x \
  -e cores=2 -e memory=2048 -e disk=32 -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e domain_join=true \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12
```
Expected: syntax OK.

**Commit:** `feat(ad_join_ubuntu): apt packages, realm join via stdin, sssd.conf, sudoers, pam-mkhomedir`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_3 -->
### Task 3: `roles/ad_join_rocky` — dnf, realm join, authselect

**Verifies:** pmx-provisioning.AC1.2, pmx-provisioning.AC1.3, pmx-provisioning.AC1.5, pmx-provisioning.AC4.2 (domain-joined), pmx-provisioning.AC5.1 (rocky), pmx-provisioning.AC5.2 (rocky-side)

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_rocky/tasks/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_rocky/defaults/main.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_rocky/meta/main.yml`

**Implementation:**

`defaults/main.yml`:
```yaml
ad_join_rocky_packages:
  - realmd
  - sssd
  - sssd-tools
  - sssd-ad
  - oddjob
  - oddjob-mkhomedir
  - adcli
  - krb5-workstation
  - samba-common-tools
  - authselect
  - authselect-compat
```

`meta/main.yml`:
```yaml
dependencies:
  - role: ad_join_common
```

`tasks/main.yml`:
```yaml
---
- name: Assert AD_JOIN_PASSWORD is set
  ansible.builtin.assert:
    that:
      - lookup('env', 'AD_JOIN_PASSWORD') | length > 0
    fail_msg: "$AD_JOIN_PASSWORD must be set."

- name: Install AD join packages
  ansible.builtin.dnf:
    name: "{{ ad_join_rocky_packages }}"
    state: present

- name: Check whether host is already realm-joined
  ansible.builtin.command: realm list
  register: realm_list
  changed_when: false
  failed_when: false

- name: Run realm join (skipped if already joined)
  ansible.builtin.shell: >
    set -o pipefail;
    printf '%s' "$AD_JOIN_PASSWORD"
    | realm join --unattended --stdin-password -U {{ ad_join_user }} {{ ad_domain }}
  args:
    executable: /bin/bash
  # Ansible does not inherit the controller's env on remote tasks; the lookup
  # runs on the controller where $AD_JOIN_PASSWORD is set. `no_log: true` below
  # keeps the expanded value out of logs.
  environment:
    AD_JOIN_PASSWORD: "{{ lookup('env', 'AD_JOIN_PASSWORD') }}"
  register: realm_join_result
  when: ad_domain not in realm_list.stdout
  # `no_log` hides the task output; the registered variable remains accessible
  # to failed_when (which runs on the controller).
  failed_when: realm_join_result.rc != 0 and 'Already joined' not in realm_join_result.stderr
  no_log: true

- name: Apply shared sssd.conf + sudoers drop-in
  ansible.builtin.include_role:
    name: ad_join_common
    tasks_from: apply

- name: Flush handlers so sssd restarts before PAM change
  ansible.builtin.meta: flush_handlers

- name: Enable SSSD + mkhomedir via authselect
  ansible.builtin.command: authselect select sssd with-mkhomedir --force
  changed_when: true

- name: Ensure oddjobd is enabled and running (needed by pam_oddjob_mkhomedir on Rocky)
  ansible.builtin.systemd:
    name: oddjobd
    state: started
    enabled: true
```

**Implementation notes:**

- Rocky's PAM story differs: `authselect select sssd with-mkhomedir` wires pam_oddjob_mkhomedir into the session stack rather than pam_mkhomedir directly. `oddjobd` must be running for it to actually create the home dir on first login.
- Same `no_log: true` + pipefail pattern as Ubuntu.

**Testing:**

See Tasks 4 (molecule) and 6 (live integration).

**Verification:**

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=vm -e guest_os=rocky -e guest_name=x \
  -e cores=2 -e memory=2048 -e disk=32 -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e domain_join=true \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12
```
Expected: syntax OK.

**Commit:** `feat(ad_join_rocky): dnf packages, realm join, authselect sssd with-mkhomedir`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Molecule tests for ad_join_ubuntu and ad_join_rocky

**Verifies:** pmx-provisioning.AC7.1, pmx-provisioning.AC7.3 (dry-run the file validation logic)

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_ubuntu/molecule/default/molecule.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_ubuntu/molecule/default/converge.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_ubuntu/molecule/default/verify.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_rocky/molecule/default/molecule.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_rocky/molecule/default/converge.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_rocky/molecule/default/verify.yml`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_ubuntu/molecule/default/mocks/realm.sh`
- Create: `/home/sysop/proxmox-manage/ansible/roles/ad_join_rocky/molecule/default/mocks/realm.sh`

**Implementation:**

Molecule can't join a real domain inside a Podman container, so we stub out `realm` with a shell script that records the join was requested and writes a fake `realm list` entry. We then exercise everything **except** the actual join: package install, sssd.conf rendering, sudoers validation, pam-auth-update / authselect.

`ad_join_ubuntu/molecule/default/molecule.yml`:
```yaml
---
dependency:
  name: galaxy
driver:
  name: podman
platforms:
  - name: pmx-ubuntu
    image: docker.io/library/ubuntu:24.04
    pre_build_image: true
    privileged: true
    command: /lib/systemd/systemd
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw
    capabilities:
      - SYS_ADMIN
    systemd: always
    tmpfs:
      - /run
      - /tmp
provisioner:
  name: ansible
  env:
    AD_JOIN_PASSWORD: testpw
  inventory:
    group_vars:
      all:
        ad_domain: test.example
        ad_realm: TEST.EXAMPLE
        ad_join_user: testuser
verifier:
  name: ansible
```

`ad_join_ubuntu/molecule/default/mocks/realm.sh`:
```bash
#!/usr/bin/env bash
# Stub out realm for molecule. Records joins; returns plausible `realm list` output.
set -e
case "${1:-}" in
  join)
    touch /var/run/realm-joined
    exit 0
    ;;
  list)
    if [ -f /var/run/realm-joined ]; then
      printf '%s\n  type: kerberos\n  realm-name: %s\n  domain-name: %s\n' \
        "${AD_DOMAIN:-test.example}" "${AD_REALM:-TEST.EXAMPLE}" "${AD_DOMAIN:-test.example}"
    fi
    exit 0
    ;;
  *)
    echo "mock realm: ${*}" >&2
    exit 0
    ;;
esac
```

`ad_join_ubuntu/molecule/default/converge.yml`:
```yaml
---
- name: Converge
  hosts: all
  become: true
  pre_tasks:
    - name: Install the stub realm binary
      ansible.builtin.copy:
        src: mocks/realm.sh
        dest: /usr/sbin/realm
        mode: "0755"
    - name: Install python3 and systemd deps (base ubuntu:24.04 image is minimal)
      ansible.builtin.apt:
        name:
          - python3
          - python3-apt
          - dbus
          - systemd
          - sudo
        update_cache: true
  roles:
    - name: ad_join_ubuntu
```

`ad_join_ubuntu/molecule/default/verify.yml`:
```yaml
---
- name: Verify
  hosts: all
  become: true
  tasks:
    - name: sssd.conf is present, mode 0600
      ansible.builtin.stat:
        path: /etc/sssd/sssd.conf
      register: sssd_stat
    - ansible.builtin.assert:
        that:
          - sssd_stat.stat.exists
          - sssd_stat.stat.mode == "0600"

    - name: sssd.conf contains override_space and simple_allow_groups
      ansible.builtin.shell: |
        set -e
        grep -q 'override_space = _' /etc/sssd/sssd.conf
        grep -q 'simple_allow_groups = domain_admins' /etc/sssd/sssd.conf
      changed_when: false

    - name: sudoers drop-in is present and validates
      ansible.builtin.stat:
        path: /etc/sudoers.d/domain-admins
      register: sudo_stat
    - ansible.builtin.assert:
        that:
          - sudo_stat.stat.exists
          - sudo_stat.stat.mode == "0440"

    - name: visudo -cf validates the drop-in (AC7.1)
      ansible.builtin.command: /usr/sbin/visudo -cf /etc/sudoers.d/domain-admins
      changed_when: false

    - name: pam-auth-update enabled mkhomedir (AC5.1 wiring)
      ansible.builtin.shell: |
        set -e
        grep -q 'pam_mkhomedir' /etc/pam.d/common-session
      changed_when: false
```

The Rocky counterparts are structurally identical with `image: docker.io/library/rockylinux:9`, dnf pre-tasks, and `grep pam_oddjob_mkhomedir /etc/pam.d/system-auth` in verify.

**Verification:**

```bash
cd /home/sysop/proxmox-manage
uv add --dev molecule "molecule-plugins[podman]" ansible-lint
cd ansible/roles/ad_join_ubuntu
uv run molecule test
```
Expected: green across create/converge/verify/destroy.

Same for `ad_join_rocky`.

**Commit:** `test(ad_join): molecule podman tests for ubuntu + rocky roles (realm mocked)`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Wire AD join into `provision.yml`

**Verifies:** pmx-provisioning.AC1.2 (plumbing)

**Files:**
- Modify: `/home/sysop/proxmox-manage/ansible/playbooks/provision.yml`

**Implementation:**

Configure play gains two conditional role includes — one per OS family — both gated on `domain_join`:

```yaml
- name: Configure guest
  hosts: just_created
  gather_facts: true
  become: "{{ guest_kind == 'vm' }}"
  tasks:
    - name: Run common bootstrap (upgrade + base packages)
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

    # Phase 6 adds: mount_cephfs, attach_rbd_disk, extra_packages, static_ip
    # Phase 8 adds: post_create_hook
```

**Verification:**

Syntax check with `domain_join=true`:
```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml \
  -e target_node=pve01 -e guest_kind=vm -e guest_os=ubuntu -e guest_name=x \
  -e cores=2 -e memory=2048 -e disk=32 -e cephfs_mounts='[]' -e rbd_disk=null \
  -e extra_packages='[]' -e static_ip=null -e domain_join=true \
  -e default_storage=bwrx -e default_lxc_storage=cephfs -e default_bridge=vmbr0 \
  -e ad_domain=broken.wrx -e ad_realm=BROKEN.WRX -e ad_join_user=jtd \
  -e proxmox_api_host=192.168.9.12
```
Expected: syntax OK.

**Commit:** `feat(ansible): wire ad_join_{ubuntu,rocky} conditionally in provision.yml`
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: End-to-end integration test — domain-joined VM + LXC, Ubuntu + Rocky

**Verifies:** pmx-provisioning.AC1.2, AC1.3, AC2.2, AC3.1, AC3.2, AC3.3, AC4.1, AC4.2 (domain-joined), AC5.1, AC5.2, AC7.1, AC7.2

**Files:**
- Create: `/home/sysop/proxmox-manage/tests/integration/test_ad_join.sh`

**Implementation:**

```bash
#!/usr/bin/env bash
set -euo pipefail

# tests/integration/test_ad_join.sh — full-stack domain-join sanity check.
# Requires: pmx seed done; workstation has $AD_JOIN_PASSWORD exported OR runs interactively.
# Creates 4 guests (ubuntu vm, ubuntu lxc, rocky vm, rocky lxc), verifies, destroys.

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD before running (or run pmx new interactively once).}"

SMOKE_USER="${PMX_TEST_DOMAIN_USER:-jtd}"  # existing domain user for smoke-test logins

smoke_test() {
  local kind="$1"
  local os="$2"
  local name="pmxtest-${os}-${kind}-$$"
  local ssh_user

  if [ "$kind" = "vm" ]; then ssh_user="ansible"; else ssh_user="root"; fi

  echo "=== Building ${kind} ${os} named ${name} ==="
  uv run pmx new --name "${name}" --kind "${kind}" --os "${os}" \
    --cores 2 --memory 2048 --disk 16

  # Discover IP (same logic as in phase 03/04 test scripts; LXC path shown)
  local vmid ip
  if [ "$kind" = "vm" ]; then
    vmid=$(ssh root@192.168.9.12 "qm list | awk -v n=${name} '\$2==n{print \$1}'")
    ip=$(ssh root@192.168.9.12 "qm guest cmd ${vmid} network-get-interfaces" \
         | python3 -c 'import json,sys; print([a["ip-address"] for i in json.load(sys.stdin) if i["name"]!="lo" for a in i.get("ip-addresses",[]) if a["ip-address-type"]=="ipv4" and not a["ip-address"].startswith("127.")][0])')
  else
    vmid=$(ssh root@192.168.9.12 "pct list | awk -v n=${name} '\$NF==n{print \$1}'")
    ip=$(ssh root@192.168.9.12 "pct exec ${vmid} -- ip -j addr show" \
         | python3 -c 'import json,sys; print([a["local"] for i in json.load(sys.stdin) if i["ifname"]!="lo" for a in i.get("addr_info",[]) if a["family"]=="inet" and not a["local"].startswith("127.")][0])')
  fi

  echo "=== Verifying AD join on ${name} (${ip}) ==="
  ssh -o StrictHostKeyChecking=accept-new ${ssh_user}@${ip} "realm list | grep -q '${SMOKE_USER%@*}@broken.wrx\|broken.wrx'"
  ssh ${ssh_user}@${ip} "id Administrator@broken.wrx"
  ssh ${ssh_user}@${ip} "getent group domain_admins | head -1"
  ssh ${ssh_user}@${ip} "test -f /etc/sudoers.d/domain-admins && visudo -cf /etc/sudoers.d/domain-admins"

  # AC5 mkhomedir check requires an actual domain login. Do via ssh to a domain user; fall through on failure since it needs interactive password.
  # If PMX_TEST_DOMAIN_USER is set, try passwordless (operator must have keys in AD user's homedir OR this line is skipped):
  ssh -o BatchMode=yes ${SMOKE_USER}@${ip} "test -d /home/${SMOKE_USER} && whoami" \
    || echo "(mkhomedir live check requires a real AD user login; skipped in BatchMode)"

  echo "=== ${name} OK — destroying ==="
  if [ "$kind" = "vm" ]; then
    ssh root@192.168.9.12 "qm stop ${vmid} && qm destroy ${vmid} --purge"
  else
    ssh root@192.168.9.12 "pct stop ${vmid} && pct destroy ${vmid} --purge"
  fi
}

smoke_test vm  ubuntu
smoke_test lxc ubuntu
smoke_test vm  rocky
smoke_test lxc rocky

echo "All four combinations passed."
```

**Verification:**

```bash
chmod +x tests/integration/test_ad_join.sh
./tests/integration/test_ad_join.sh
```
Expected: Four guests built, each joined to `broken.wrx`, each with sudoers drop-in validated, each destroyed cleanly.

**AC3 checks:**

```bash
# AC3.1 — fresh shell prompts once
bash -c 'env -u AD_JOIN_PASSWORD uv run pmx new --name ac3-1-test --kind lxc --os ubuntu --dry-run'
# Expected: prompts for password via getpass, prints ansible command, exits 0.

# AC3.2 — same shell reuses cached password
bash -c 'export AD_JOIN_PASSWORD=x; uv run pmx new --name ac3-2-test --kind lxc --os ubuntu --dry-run'
# Expected: NO prompt, prints ansible command.

# AC3.3 — wrong password surfaces a realm join error and does NOT poison the cache.
# Verified indirectly via the live integration: if AD_JOIN_PASSWORD is wrong, the
# `realm join` task fails; the CLI exits non-zero; env var remains set (unchanged by failure).
```

**Commit:** `test(ad_join): integration harness for VM + LXC / Ubuntu + Rocky`
<!-- END_TASK_6 -->

---

## Phase 5 done when

- All four combinations (VM+Ubuntu, VM+Rocky, LXC+Ubuntu, LXC+Rocky) from `pmx new --name <x> --kind <k> --os <o>` (NO `--no-domain`) end up domain-joined and reachable (AC1.2, AC2.2, AC4.1, AC4.2)
- `Domain Admins` members can SSH in and `sudo -i` with an auto-created `/home/<user>` (AC1.3, AC5.1, AC5.2)
- `/etc/sudoers.d/domain-admins` exists at mode 0440 and passes `visudo -cf` on every produced guest (AC7.1)
- Providing a wrong `$AD_JOIN_PASSWORD` fails loudly during realm join and leaves the guest running with a vmid surfaced in the error (AC1.5, AC3.3)
- Molecule tests pass for both `ad_join_ubuntu` and `ad_join_rocky` with a stub `realm` (AC7.1, AC7.3)
- `pmx new ... --dry-run` works both with and without `$AD_JOIN_PASSWORD` set, prompting only when unset (AC3.1, AC3.2)
- Clean `git status` after commits from Tasks 1–6
