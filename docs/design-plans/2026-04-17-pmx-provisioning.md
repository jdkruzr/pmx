# pmx — Proxmox Provisioning CLI Design

## Summary

`pmx` is a Python CLI that wraps Ansible to automate provisioning of Proxmox VMs and LXC containers on a single cluster. The operator runs a single `pmx new` command from their workstation; the tool handles Proxmox guest creation, OS configuration, Active Directory domain join, and optional Ceph storage attachment — producing a fully usable, SSH-reachable guest in one step.

The architecture splits into two Ansible play phases invoked by the CLI. The create phase runs against the Proxmox cluster nodes via the `community.proxmox` collection to clone or instantiate the guest from seed templates, and for LXC it also writes the UID/GID map extensions needed for SSSD's high UIDs to resolve. The configure phase runs against the new guest itself: it applies a common role, then conditionally applies OS-specific AD-join roles (driving `realm join` and writing an opinionated `sssd.conf`), and optional add-on roles for CephFS mounts, extra disks, and extra packages. Click handles flag parsing and the one-per-session AD credential prompt; Ansible carries all idempotent state logic; an append-only `state/guests.jsonl` file records each build for use by lifecycle commands and future DHCP integration.

## Definition of Done

The project is done when:

1. A single command (`pmx new --name foo --os ubuntu --kind vm --cores 4 --memory 8192 --disk 64`) produces a running, SSH-reachable VM on the Proxmox cluster that is already joined to the `broken.wrx` Samba AD domain, with `Domain Admins` members able to `sudo`, and home directories created on first login.
2. The same command with `--kind lxc` produces an **unprivileged** LXC container that is domain-joined, with the UID/GID map extended so SSSD's high UIDs resolve correctly — no falling back to privileged containers.
3. Both **Ubuntu 24.04** and **Rocky 9** work equivalently as guest OS, selectable by flag.
4. The AD join password is prompted once per shell session (hidden input), cached in `$AD_JOIN_PASSWORD`, and used for subsequent builds without re-prompting.
5. Build-time options include `--cephfs <subpath>:<guest-path>` (repeatable, handled VM-native or LXC-passthrough automatically), `--rbd-disk <size>`, `--extra-packages`, `--static-ip <addr>/<cidr>`, and `--no-domain`.
6. `pmx destroy <name>` cleanly removes the AD computer account (via `adcli delete-computer`) and then destroys the guest.
7. `pmx reconfigure <name>` is idempotent and re-runs only the configure phase against an existing guest.
8. `pmx verify <name>` runs a live smoke test (`id Administrator@broken.wrx`, sudo check) and exits non-zero on failure.
9. `pmx seed` is a one-shot bootstrap that produces the required VM templates and LXC template from upstream cloud images, and is safe to re-run.
10. Every successful build appends a record to `state/guests.jsonl` with `{hostname, vmid, mac, ip, kind, os}` — providing the seam for future Zentyal DHCP reservation wiring without requiring architectural changes.
11. Core roles have molecule tests; the CLI has a live integration smoke test against the real cluster (behind an env flag so CI doesn't run it).

## Acceptance Criteria

### pmx-provisioning.AC1: VM creation with AD join works end-to-end
- **pmx-provisioning.AC1.1 Success:** VM created with specified resources, SSH-reachable within 120s of `pmx new`
- **pmx-provisioning.AC1.2 Success:** Domain-joined; `id Administrator@broken.wrx` resolves on the guest
- **pmx-provisioning.AC1.3 Success:** `Domain Admins` member can `ssh` in and `sudo -i` with auto-created `/home/<user>`
- **pmx-provisioning.AC1.4 Failure:** `pmx new --name <existing>` refuses with a clear error (names are primary key)
- **pmx-provisioning.AC1.5 Failure:** realm join failure leaves guest running and surfaces vmid for recovery

### pmx-provisioning.AC2: Unprivileged LXC with UID-map fix
- **pmx-provisioning.AC2.1 Success:** LXC created as unprivileged; `cat /proc/self/uid_map` inside shows extended range covering SSSD's ~5e8 UIDs
- **pmx-provisioning.AC2.2 Success:** `id Administrator@broken.wrx` resolves inside the LXC (no fallback to privileged)
- **pmx-provisioning.AC2.3 Success:** Ceph pass-through mounts are visible in the LXC at the declared path
- **pmx-provisioning.AC2.4 Failure:** If idmap write to `/etc/pve/lxc/<vmid>.conf` fails, creation bails before start

### pmx-provisioning.AC3: AD credential prompt and caching
- **pmx-provisioning.AC3.1 Success:** First invocation in a fresh shell prompts once (hidden input via getpass)
- **pmx-provisioning.AC3.2 Success:** Subsequent invocations in same shell reuse `$AD_JOIN_PASSWORD` silently
- **pmx-provisioning.AC3.3 Failure:** Wrong password surfaces a realm-join error and does NOT poison the cache

### pmx-provisioning.AC4: Ubuntu and Rocky both first-class
- **pmx-provisioning.AC4.1 Success:** `--os ubuntu` builds a working domain-joined Ubuntu 24.04 guest (VM and LXC)
- **pmx-provisioning.AC4.2 Success:** `--os rocky` builds a working domain-joined Rocky 9 guest (VM and LXC)
- **pmx-provisioning.AC4.3 Success:** Both pass `pmx verify` with identical criteria

### pmx-provisioning.AC5: pam-auth-update mkhomedir default-on
- **pmx-provisioning.AC5.1 Success:** First SSH login as a domain user creates `/home/<user>` with correct ownership
- **pmx-provisioning.AC5.2 Success:** Behavior is consistent on both Ubuntu and Rocky guests

### pmx-provisioning.AC6: pmx seed bootstrap
- **pmx-provisioning.AC6.1 Success:** Empty cluster produces one Ubuntu VM template, one Rocky VM template, and the Rocky LXC template cached
- **pmx-provisioning.AC6.2 Success:** Re-running `pmx seed` is a no-op (idempotent)
- **pmx-provisioning.AC6.3 Edge:** Partial prior state (e.g., only Ubuntu template exists) completes only the missing work

### pmx-provisioning.AC7: Sudoers drop-in
- **pmx-provisioning.AC7.1 Success:** `/etc/sudoers.d/domain-admins` exists, mode 0440, validates with `visudo -cf`
- **pmx-provisioning.AC7.2 Success:** `domain_admins` members can `sudo` without backslash-space parsing errors
- **pmx-provisioning.AC7.3 Failure:** If `visudo -cf` fails, the drop-in file is rolled back

### pmx-provisioning.AC8: --cephfs mount option
- **pmx-provisioning.AC8.1 Success:** VM: `ceph-common` installed, fstab entry added, mount live at specified path, survives reboot
- **pmx-provisioning.AC8.2 Success:** LXC: path mounted on host (if not already), `mp<N>:` pass-through line added to container config; no `ceph-common` installed inside
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

### pmx-provisioning.AC15: State log (DHCP seam)
- **pmx-provisioning.AC15.1 Success:** Every successful build appends one JSON line to `state/guests.jsonl` with `{hostname, vmid, mac, ip, kind, os, domain_joined}`
- **pmx-provisioning.AC15.2 Success:** Log is append-only; old entries preserved
- **pmx-provisioning.AC15.3 Edge:** Missing log file is created on first build

### pmx-provisioning.AC16: Post-create hook contract
- **pmx-provisioning.AC16.1 Success:** `post_create_hook` role receives `{hostname, vmid, mac, ip, kind, os, domain_joined}` variables
- **pmx-provisioning.AC16.2 Success:** Default implementation writes state log only (no other side effects)
- **pmx-provisioning.AC16.3 Documentation:** `docs/extending-post-create.md` describes how to plug in DHCP/DNS integrations

## Glossary

- **qm**: Proxmox command-line tool for managing QEMU/KVM virtual machines (create, clone, destroy, configure).
- **pct**: Proxmox command-line tool for managing LXC containers, the container counterpart to `qm`.
- **VMID**: Numeric identifier Proxmox assigns to every guest (VM or container); used as the primary key in Proxmox's own APIs.
- **LXC**: Linux Containers — OS-level virtualization used by Proxmox for lightweight, unprivileged containers.
- **cloud-init**: Industry-standard mechanism for injecting hostname, SSH keys, network config, and user data into a VM on first boot via a special drive.
- **CephFS**: Distributed POSIX filesystem layer on top of a Ceph cluster; used here for shared storage mounted into guests.
- **RBD**: RADOS Block Device — raw block storage exported from a Ceph cluster, attached to VMs as additional disks.
- **realmd**: System service that discovers and joins AD/Kerberos domains; `pmx` drives it via `realm join`.
- **SSSD**: System Security Services Daemon — mediates identity lookups and authentication against AD, caches credentials for offline use.
- **adcli**: Low-level command-line tool for manipulating AD computer accounts; used by `pmx destroy` to remove the computer object on teardown.
- **realm join**: The `realmd` command that enrolls a Linux host into a domain, triggering Kerberos keytab creation and SSSD configuration.
- **Kerberos**: Authentication protocol underlying AD; `pmx` stores tickets via SSSD's `krb5_store_password_if_offline` for offline resilience.
- **UID mapping**: In unprivileged LXC, host UIDs are remapped to a safe range inside the container; the `lxc.idmap` range must be extended to cover SSSD's high UIDs (~5×10⁸) or domain users will not resolve.
- **Ansible roles**: Self-contained units of Ansible automation (tasks, templates, handlers) that can be composed; each functional concern (`ad_join_ubuntu`, `mount_cephfs`, etc.) is its own role.
- **community.proxmox collection**: Ansible collection providing `proxmox_kvm` (VM lifecycle) and `proxmox` (LXC lifecycle) modules; the canonical interface between Ansible and the Proxmox API.
- **Click CLI**: Python library for building command-line interfaces; used here for flag parsing, subcommand dispatch, and the hidden-input credential prompt.
- **molecule**: Ansible role testing framework; spins up throwaway containers to run and verify role tasks in isolation.

## Architecture

`pmx` is a Python CLI (Click-based) that runs on the operator's workstation. It parses flags, handles the one-time AD-credential prompt per shell session, and shells out to `ansible-playbook` with extra-vars. All Proxmox state lives in Proxmox itself (no separate state store beyond the append-only `state/guests.jsonl` log used as a DHCP-wiring seam).

The top-level playbook `playbooks/provision.yml` runs in two phases:

1. **Create phase** — runs against a static `proxmox` inventory group of cluster nodes. Uses `community.proxmox.proxmox_kvm` (VMs) or `community.proxmox.proxmox` (LXC) to clone or create the guest. For LXC, the role additionally writes UID/GID map extensions to `/etc/pve/lxc/<vmid>.conf` and matching entries in `/etc/subuid` / `/etc/subgid` on the target host. On completion, adds the new guest to a dynamic in-memory inventory group.

2. **Configure phase** — runs against the freshly created guest (waits for SSH reachability with exponential backoff). Applies the `common` role (OS upgrade, base packages), then one of `ad_join_ubuntu` / `ad_join_rocky` if domain join is requested, then optional add-on roles for Ceph, extra disks, and extra packages based on flags passed through as variables.

Guest creation uses **seed templates** built once by `pmx seed`: cloud-init-ready VM templates for Ubuntu 24.04 and Rocky 9 (`qm importdisk` from upstream cloud images, converted via `qm template`), plus the pulled Rocky LXC template in `cephfs:vztmpl/`. VMs are cloned from templates (`qm clone --full`); LXCs are created from the cached template (`pct create`).

The AD-join role drives `realm join --unattended` with the password piped via stdin from `{{ lookup('env','AD_JOIN_PASSWORD') }}`. It then writes an opinionated `/etc/sssd/sssd.conf` (override_space = `_`, `ldap_id_mapping = True`, `simple_allow_groups = domain_admins`, `cache_credentials = True`, `krb5_store_password_if_offline = True`, `fallback_homedir = /home/%u`), drops a `/etc/sudoers.d/domain-admins` file validated with `visudo -cf`, and runs `pam-auth-update --enable mkhomedir` non-interactively.

Ceph integration differs by guest kind. For VMs the role installs `ceph-common`, drops `/etc/ceph/ceph.conf` and a `cephfs.secret` file (sourced from the workstation's own config), and adds an fstab entry pointing at the four-mon list `192.168.9.11-14:6789`. For unprivileged LXCs the role mounts the path on the host instead and adds a `mp<N>: /host/path,mp=/guest/path` line to the container config — no `ceph-common` install inside the container.

## Existing Patterns

This is a greenfield project in an empty repository. There are no codebase patterns to follow. The design borrows conventions from the operator's existing manual runbook and the observed configuration on their workstation:

- sssd.conf fields match what's already running on the workstation (`simple_allow_groups`, `ldap_id_mapping`, `access_provider = simple`, etc.). The only opinionated change from the observed config is adding `override_space = _` so downstream rules never have to deal with spaces in group names.
- Ceph mount syntax (`secretfile=/etc/ceph/cephfs.secret`, kernel cephfs client, mon list `192.168.9.11-14:6789`) is lifted directly from the operator's `/etc/fstab`.
- Sudoers drop-ins land in `/etc/sudoers.d/` (which is currently empty on the workstation) rather than editing `/etc/sudoers`, because the drop-in approach sidesteps the backslash-space parsing regression in recent sudo.

Research established the two load-bearing external patterns used:

- **LXC UID-map extension for SSSD:** Unprivileged LXC domain-join works when the container's `lxc.idmap` ranges cover SSSD's high UIDs (~5×10⁸). The fix is not AppArmor — it's extending `/etc/pve/lxc/<vmid>.conf` + host `subuid`/`subgid`. Documented in Proxmox forum threads and community notes.
- **Ansible `community.proxmox` collection** as the canonical module set for both VM and LXC lifecycle (split out from `community.general` in recent versions).

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Repository scaffolding and `pmx` CLI shell

**Goal:** Project layout, dependencies, and the CLI entrypoint with flag parsing, help text, and the AD-credential prompt/env-cache logic — but no provisioning yet. All subcommands exist as stubs that print "not yet implemented."

**Components:**
- `pyproject.toml` with Click, ansible-core, proxmoxer as deps
- `pmx/cli.py` — Click root command, subcommands `new`, `destroy`, `reconfigure`, `verify`, `seed` as stubs
- `pmx/credentials.py` — `$AD_JOIN_PASSWORD` env lookup + getpass prompt fallback
- `pmx/config.py` — loads workstation config (`~/.config/pmx/config.yml` for Proxmox API URL, node SSH alias, default storage pool, default bridge)
- `ansible/ansible.cfg`, `ansible/inventory/proxmox.yml`, `ansible/group_vars/proxmox.yml`
- `ansible/playbooks/provision.yml` as an empty skeleton with `create` and `configure` plays

**Dependencies:** None

**Done when:** `pmx --help` lists all subcommands, `pmx new --help` shows every flag, running `pmx new --name test` prompts for the AD password (hidden), caches it in env, and exits cleanly with a "not yet implemented" marker. `ansible --version` resolves the installed core version. Infrastructure-level verification — no unit tests required.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: `pmx seed` bootstrap

**Goal:** One-shot command that prepares the cluster with the seed VM templates and LXC template this tool needs. Idempotent — re-running skips what already exists.

**Components:**
- `pmx/seed.py` — orchestrates template creation by SSHing to a nominated node
- `ansible/roles/seed_ubuntu_vm/` — downloads Ubuntu 24.04 cloud image, `qm create` with cloud-init drive, `qm importdisk`, `qm template`
- `ansible/roles/seed_rocky_vm/` — same for Rocky 9 cloud image
- `ansible/roles/seed_rocky_lxc/` — runs `pveam download cephfs rockylinux-9-default_*.tar.xz`
- `ansible/playbooks/seed.yml` — top-level playbook wiring these roles

**Dependencies:** Phase 1 (CLI and playbook skeleton exist)

**Done when:** `pmx seed` run against an empty cluster produces one Ubuntu VM template and one Rocky VM template (visible in `qm list --full`) and downloads the Rocky LXC template (visible in `pveam list cephfs`). Re-running the command exits quickly with no changes. Infrastructure verification — no unit tests. Covers ACs: `pmx-provisioning.AC6.*` (seed idempotency).
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: VM creation path (no domain join yet)

**Goal:** `pmx new --kind vm` produces a running, SSH-reachable VM cloned from the seed template with cloud-init applying hostname, SSH keys, and DHCP networking. Configure phase runs `common` role only.

**Components:**
- `ansible/roles/create_vm/` — calls `community.proxmox.proxmox_kvm` with `clone:` + cloud-init args, polls QGA/SSH for readiness
- `ansible/roles/common/` — apt upgrade, base packages (tmux, python3, ca-certificates, ...)
- `pmx/cli.py` — wires `new --kind vm` to the playbook with extra-vars for name, cores, mem, disk, os
- Dynamic inventory handoff so configure phase runs against the new guest

**Dependencies:** Phase 2 (seed templates exist)

**Done when:** `pmx new --name testvm --kind vm --os ubuntu --cores 2 --memory 2048 --disk 32 --no-domain` produces a running, SSH-reachable Ubuntu VM with the right resources and the operator's SSH key installed. Same for `--os rocky`. Tests: integration test that creates a throwaway VM, asserts SSH reachability and cloud-init completion, then destroys it. Covers ACs: `pmx-provisioning.AC1.*` (VM creation success), `pmx-provisioning.AC4.*` (both OS families work).
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: LXC creation path with UID-map fix

**Goal:** `pmx new --kind lxc` produces a running, SSH-reachable unprivileged LXC with an extended UID/GID map suitable for SSSD. Configure phase runs `common` role only.

**Components:**
- `ansible/roles/create_lxc/` — calls `community.proxmox.proxmox` for create, then writes UID-map block to `/etc/pve/lxc/<vmid>.conf`, and appends matching ranges to `/etc/subuid` / `/etc/subgid` on the host
- Template discovery logic (pick the latest Ubuntu or Rocky LXC template from the cache)
- Feature flags: `unprivileged=1`, `features=nesting=1,keyctl=1`
- `pmx/cli.py` wires `new --kind lxc`

**Dependencies:** Phase 3 (common role and inventory handoff exist)

**Done when:** `pmx new --name testlxc --kind lxc --os ubuntu --no-domain` (and `--os rocky`) produces an unprivileged LXC, SSH-reachable, where `cat /proc/self/uid_map` inside the container shows the extended range. Integration test creates, asserts, destroys. Covers ACs: `pmx-provisioning.AC2.*` (unprivileged LXC creation), `pmx-provisioning.AC4.*`.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: AD join roles (Ubuntu + Rocky)

**Goal:** Domain join happens automatically on both VMs and LXCs, on both OS families, end-to-end. This is the core value delivery phase.

**Components:**
- `ansible/roles/ad_join_ubuntu/` — installs realmd, sssd, sssd-tools, krb5-user, adcli, packagekit; runs `realm join --unattended -U jtd broken.wrx` piping `$AD_JOIN_PASSWORD`; templates `/etc/sssd/sssd.conf`; drops `/etc/sudoers.d/domain-admins` (validated); runs `pam-auth-update --enable mkhomedir`
- `ansible/roles/ad_join_rocky/` — same flow with dnf packages (realmd, sssd, oddjob, oddjob-mkhomedir, adcli, krb5-workstation, samba-common-tools)
- `ansible/roles/ad_join_common/` — shared `sssd.conf.j2` template, shared sudoers drop-in template, shared post-join SSSD restart handler
- Playbook wiring so `--no-domain` skips this role

**Dependencies:** Phase 4 (both create paths exist)

**Done when:** `pmx new --name ub-joined --os ubuntu` (VM and LXC variants) produces a guest where `id Administrator@broken.wrx` resolves, `getent group domain_admins` returns members, and an SSH session as a domain user lands in an auto-created home directory and can `sudo`. Same for Rocky. Molecule tests for each of the two OS-specific roles against a throwaway container. Covers ACs: `pmx-provisioning.AC1.*`, `pmx-provisioning.AC2.*` (now end-to-end with AD), `pmx-provisioning.AC3.*` (credential caching), `pmx-provisioning.AC5.*` (pam mkhomedir), `pmx-provisioning.AC7.*` (sudoers drop-in).
<!-- END_PHASE_5 -->

<!-- START_PHASE_6 -->
### Phase 6: Build options — Ceph, RBD, extras, static IP

**Goal:** The four additional build-time options work on both kinds and both OS families.

**Components:**
- `ansible/roles/mount_cephfs/` — branches on guest kind. VM: installs `ceph-common`, drops `/etc/ceph/ceph.conf` + `cephfs.secret` from workstation sources, adds fstab entry, mounts. LXC: mounts on host if not already mounted, patches `/etc/pve/lxc/<vmid>.conf` with `mp<N>:` pass-through line
- `ansible/roles/attach_rbd_disk/` — VM-only. Uses `community.proxmox.proxmox_disk` (or raw `qm set` fallback) to add an RBD volume from the `bwrx` pool
- `ansible/roles/extra_packages/` — apt or dnf list from extra-var
- `ansible/roles/static_ip/` — VM: cloud-init ipconfig0 override. LXC: `pct set --net0` with static config
- `pmx/cli.py` wires all four flags

**Dependencies:** Phase 5 (end-to-end build works for the simple case)

**Done when:** A single invocation `pmx new --name kitchen-sink --kind vm --os ubuntu --cephfs supernote:/mnt/sn --rbd-disk 50 --extra-packages htop,jq --static-ip 192.168.9.80/24` produces a VM with the CephFS mount live, an extra 50G disk attached, `htop`/`jq` installed, and the specified static IP. LXC variant produces the same except the CephFS mount is passed through from the host. Covers ACs: `pmx-provisioning.AC8.*` (cephfs), `pmx-provisioning.AC9.*` (rbd-disk), `pmx-provisioning.AC10.*` (extra-packages), `pmx-provisioning.AC11.*` (static-ip).
<!-- END_PHASE_6 -->

<!-- START_PHASE_7 -->
### Phase 7: Destroy, reconfigure, verify

**Goal:** The lifecycle commands beyond creation. These turn the tool from "build script" into something operable.

**Components:**
- `pmx destroy <name>` — confirms, calls `adcli delete-computer` from a trusted existing host (or from inside the guest before teardown) using cached `$AD_JOIN_PASSWORD`, then `qm destroy` or `pct destroy`. Skips adcli with a warning if `--no-domain` was used at build time (tracked via `state/guests.jsonl`)
- `pmx reconfigure <name>` — re-runs the configure phase against an existing guest. Uses `state/guests.jsonl` to recover build parameters (OS, cephfs mounts, etc.)
- `pmx verify <name>` — SSHes to the guest, runs `id Administrator@broken.wrx`, runs `sudo -n -l -U Administrator@broken.wrx` or equivalent, runs `systemctl is-active sssd`; exits non-zero if any check fails

**Dependencies:** Phase 6 (we now have full build parameter surface to preserve)

**Done when:** A VM built in Phase 5/6 can be `pmx reconfigure`d with no-op second run (idempotency), `pmx verify`d with a clean pass, and `pmx destroy`d with the AD computer object actually removed (verified by checking it's gone from the Zentyal directory). Covers ACs: `pmx-provisioning.AC12.*` (destroy cleanup), `pmx-provisioning.AC13.*` (reconfigure idempotent), `pmx-provisioning.AC14.*` (verify smoke test).
<!-- END_PHASE_7 -->

<!-- START_PHASE_8 -->
### Phase 8: Post-create hook and state log (DHCP seam)

**Goal:** The seam for future Zentyal DHCP reservation wiring is in place and exercised. The hook role is empty today but is called with the right data; state is logged.

**Components:**
- `ansible/roles/post_create_hook/` — runs at end of configure phase with variables `{hostname, vmid, mac, ip, kind, os, domain_joined}`. Default behavior: append one JSON line to `state/guests.jsonl` on the workstation. Intentionally otherwise empty.
- `pmx/state.py` — small helper to read back state for `reconfigure`/`destroy` (already used in Phase 7; this phase formalizes the write path)
- Brief note in `docs/` describing where Zentyal DHCP integration would plug in (replace body of `post_create_hook`)

**Dependencies:** Phase 7 (destroy/reconfigure already read state; this phase owns the write path)

**Done when:** Every successful `pmx new` appends a well-formed JSON line to `state/guests.jsonl`. The log is the sole thing `destroy`/`reconfigure` rely on for recovered parameters. A placeholder `docs/extending-post-create.md` describes the hook contract. Covers ACs: `pmx-provisioning.AC15.*` (state log written), `pmx-provisioning.AC16.*` (hook contract documented).
<!-- END_PHASE_8 -->

## Additional Considerations

**Error handling.** Three classes of failures are called out explicitly:

- *Creation failures* (Proxmox API error, storage full, etc.) bail immediately with raw `qm`/`pct` output. No partial guest is left behind where avoidable; if one is, the error tells the operator how to clean up by vmid.
- *Post-boot wait failures* (guest never becomes SSH-reachable within timeout) leave the guest running and surface the vmid so the operator can investigate via the Proxmox console. `pmx reconfigure` can resume once the guest is reachable.
- *Configure failures* (apt lock, DNS flake, realm join transient error) leave the guest running. Realm join retries once on known-transient errors. All other configure failures leave the guest in "created but not configured" state, recoverable with `pmx reconfigure`.

**Edge cases.**
- `pmx new --name <existing>` refuses with a clear message (names are the primary key). VMID is always allocated fresh via `GET /cluster/nextid`.
- `pmx destroy` of a guest not in `state/guests.jsonl` (e.g., created manually) works but skips the adcli step with a warning.
- CephFS pass-through into an LXC requires the path to be mounted on the host. If it isn't, the role mounts it (idempotent against the workstation-observed fstab pattern) rather than failing.

**Future extensibility.** The `post_create_hook` role + `state/guests.jsonl` format are the designated extension points. Near-term expected uses: Zentyal DHCP reservation creation, DNS record creation (if Zentyal's DNS is used), monitoring registration. None of these require changes to the core create/configure path.

**Scope explicitly out.** No Windows guest support. No declarative / GitOps mode. No multi-cluster support (single cluster assumption is baked into the inventory). No web UI. No automatic upgrading of existing guests — `reconfigure` is for re-running the build-time configure steps, not for drift correction.
