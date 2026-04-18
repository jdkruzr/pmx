# pmx Provisioning — Human Test Plan

Generated: 2026-04-18
Companion to: `docs/implementation-plans/2026-04-18-pmx-provisioning/`

This plan covers every acceptance criterion that can't be fully proven by the
70-test automated pytest suite. It is organised as three phases:

- **Phase 1** — bootstrap seeding (destructive to lab cluster)
- **Phase 2** — run each integration harness against the live cluster
- **Phase 3** — manually-verified ACs that require a real AD user, induced
  failures, or reboot-survival checks that scripts can't reasonably cover

## Prerequisites

- Proxmox cluster reachable at `root@192.168.9.12` (passwordless SSH)
- Workstation has `/etc/ceph/cephfs.secret` and `/etc/ceph/ceph.conf`
- `uv run pytest` passes (70 unit tests — already automatic)
- Zentyal AD domain `broken.wrx` reachable; `jtd` (or equivalent) AD join account exists
- `AD_JOIN_PASSWORD` exportable for domain-join runs
- `pmx seed` has run at least once (templates 9000, 9001 exist, Rocky LXC template in cephfs)

## Phase 1: pmx seed bootstrap (AC6)

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | `ssh root@192.168.9.12 "qm destroy 9000 --purge; qm destroy 9001 --purge"` (destructive!) | Templates removed |
| 1.2 | `uv run pmx seed` | Exit 0; 2 VM templates + 1 LXC template created |
| 1.3 | `ssh root@192.168.9.12 "qm list \| grep -E '9000\|9001'"` | Both present |
| 1.4 | `ssh root@192.168.9.12 "pveam list cephfs \| grep rockylinux-9"` | Rocky LXC template present (AC6.1) |
| 1.5 | Re-run `uv run pmx seed` | Ansible recap shows `changed=0` across all three roles (AC6.2) |
| 1.6 | `ssh root@192.168.9.12 "qm destroy 9001 --purge"` then `uv run pmx seed` | Only Rocky VM role does work; Ubuntu + Rocky-LXC report `changed=0` (AC6.3) |

## Phase 2: Integration harnesses against live cluster

These bash scripts are committed but have NOT been executed during
implementation. An operator must run each once and confirm green exit.

| Step | Action | Expected | ACs exercised |
|------|--------|----------|---------------|
| 2.1 | `bash tests/integration/test_create_vm.sh` | "Both OS families passed." | AC1.1, AC4.1, AC4.2, AC11.3 |
| 2.2 | Manual cleanup per script header (`qm stop && qm destroy --purge` for each `pmxtest-ubuntu-*`, `pmxtest-rocky-*`) | VMs gone from `qm list` | — |
| 2.3 | `bash tests/integration/test_create_lxc.sh` | "Both LXC OS families passed." | AC2.1, AC4.1, AC4.2, AC11.3 |
| 2.4 | Manual LXC cleanup (`pct stop && pct destroy --purge` for `pmxtest-lxc-*`) | — | — |
| 2.5 | `export AD_JOIN_PASSWORD=<real>; bash tests/integration/test_ad_join.sh` | "All four combinations passed." (self-cleans up) | AC1.2, AC1.3, AC2.2, AC3.2 (implicit), AC4.1/4.2, AC5.2, AC7.1 |
| 2.6 | `export AD_JOIN_PASSWORD=<real>; bash tests/integration/test_kitchen_sink.sh` | "Kitchen-sink VM passed all checks" + "Kitchen-sink LXC passed all checks" | AC2.3, AC8.1, AC8.2, AC9.1, AC10.1, AC11.1, AC11.2 |
| 2.7 | `export AD_JOIN_PASSWORD=<real>; bash tests/integration/test_lifecycle.sh` | "All lifecycle tests passed." | AC12.1, AC12.2, AC12.3, AC13.1, AC14.1 |
| 2.8 | `export AD_JOIN_PASSWORD=<real>; bash tests/integration/test_state_log.sh` | "State log tests passed." | AC15.1, AC15.2, AC15.3, AC16.1, AC16.2 |

## Phase 3: Manually verified ACs

### AC1.3: Live AD user SSH + sudo + mkhomedir

Purpose: prove `pam_mkhomedir` / `pam_oddjob_mkhomedir` actually fires for a
real AD user login (molecule only greps for wiring).

1. After a domain-joined `pmx new` build (from step 2.5 harness, or a
   standalone `uv run pmx new --name ad-login-test --os ubuntu`)
2. Discover the IP via `ssh root@192.168.9.12 "qm guest cmd <vmid> network-get-interfaces"` or from `state/guests.jsonl`
3. From a workstation with a Kerberos ticket for a real AD user (or
   interactively with password): `ssh someuser@broken.wrx@<ip>`
4. Expected: login succeeds; `/home/someuser_broken.wrx` (or
   `/home/someuser@broken.wrx`) is created on first login with correct
   ownership (`stat -c '%U %G'`)
5. Run `sudo -i` or `sudo -n true`; expected: either success or password
   prompt — NOT a sudoers parse error (AC7.2)

### AC1.5: realm-join failure surfaces vmid

Purpose: validate error-path behavior when AD is unreachable mid-configure.

1. `ssh root@zentyal "systemctl stop samba-ad-dc"` (or temporarily break
   DNS for `broken.wrx`)
2. `uv run pmx new --name failtest --os ubuntu`
3. Expected: CLI exits non-zero; stderr contains VMID; `ssh root@192.168.9.12 "qm list | grep failtest"` still shows the guest running (not auto-destroyed)
4. Restore Zentyal: `ssh root@zentyal "systemctl start samba-ad-dc"`
5. `uv run pmx reconfigure failtest` — should complete successfully (also
   covers AC13.3)
6. Cleanup: `uv run pmx destroy failtest --yes`

### AC2.4: idmap write failure bails before start

1. Identify what VMID `pvesh get /cluster/nextid` will hand out, then
   `ssh root@192.168.9.12 "touch /etc/pve/lxc/<vmid>.conf && chattr +i /etc/pve/lxc/<vmid>.conf"`
2. `uv run pmx new --name idmaptest --kind lxc --os rocky --no-domain`
3. Expected: blockinfile task fails before `pct start` runs; `pct status <vmid>` reports stopped or VMID was never populated
4. Cleanup: `chattr -i`, remove file, any orphan container

### AC3.1: Fresh-shell password prompt is hidden TTY

1. Open a new shell; `unset AD_JOIN_PASSWORD`
2. `uv run pmx new --name promptest --kind vm --os ubuntu --dry-run`
3. Expected: prints `AD join password (jtd@broken.wrx): ` on stderr; typing
   chars produces no echo; pressing Enter accepts input and CLI proceeds
   with `--dry-run` output

### AC3.3: Wrong password does not poison cache

1. Fresh shell: `export AD_JOIN_PASSWORD=intentionally-wrong`
2. `uv run pmx new --name wrongpw --os ubuntu` → expect failure with vmid
   in error
3. In same shell: `unset AD_JOIN_PASSWORD; uv run pmx reconfigure wrongpw`
   → expect new prompt (not silent reuse of bad value)
4. Enter correct password → expected success
5. Cleanup: `uv run pmx destroy wrongpw --yes`

### AC7.3: visudo -cf failure rolls back sudoers drop-in

1. Edit `ansible/roles/ad_join_common/templates/sudoers-domain-admins.j2`
   to contain obviously-invalid syntax (e.g., prepend `BOGUS` or remove
   the required `ALL=(ALL)`)
2. `uv run pmx new --name visudotest --os ubuntu`
3. Expected: template task fails during `validate:` clause;
   `/etc/sudoers.d/domain-admins` either absent (first run) or unchanged
   from prior state
4. Restore template from git: `git checkout -- ansible/roles/ad_join_common/templates/sudoers-domain-admins.j2`
5. Cleanup: `uv run pmx destroy visudotest --yes`

### AC8.1: Reboot-survival of VM CephFS mount

1. After `test_kitchen_sink.sh` VM path, note the VMID and IP (192.168.9.80)
2. `ssh root@192.168.9.12 "qm reboot <vmid>"`
3. Wait 60s (until `ssh ansible@192.168.9.80 true` returns)
4. `ssh ansible@192.168.9.80 "findmnt /mnt/sn"` → expected: mount present
   (fstab entry replayed)

### AC8.3: Explicit idempotent re-run of mount_cephfs

1. After a successful `--cephfs` build: `uv run pmx reconfigure <name>`
2. Inspect ansible output: expected `changed=0` on every `mount_cephfs` task

### AC8.4: Missing `/etc/ceph/cephfs.secret` → actionable error

1. `sudo mv /etc/ceph/cephfs.secret /etc/ceph/cephfs.secret.bak`
2. `uv run pmx new --name cephfail --os ubuntu --cephfs supernote:/mnt/sn`
3. Expected: fails with message "pmx requires /etc/ceph/cephfs.secret on
   the workstation..."
4. `sudo mv /etc/ceph/cephfs.secret.bak /etc/ceph/cephfs.secret`
5. Cleanup: `uv run pmx destroy cephfail --yes` if guest was created
   pre-mount-phase

### AC10.2: Unknown package → vmid-annotated error

1. `uv run pmx new --name pkgfail --os ubuntu --extra-packages definitely-not-a-real-package-xyz`
2. Expected: non-zero exit; error message from `extra_packages` role
   includes the guest's VMID
3. Cleanup: `uv run pmx destroy pkgfail --yes`

### AC13.2: Second reconfigure reports zero changes

1. After `test_lifecycle.sh` invokes two `pmx reconfigure` calls, re-run
   manually: `uv run pmx reconfigure <name>`
2. Inspect the ansible PLAY RECAP line; expected `changed=0 failed=0` for
   all hosts

### AC13.3: Reconfigure recovers from failed configure — combined with AC1.5 procedure

### AC16.3: docs/extending-post-create.md documents the contract

1. Open `docs/extending-post-create.md`
2. Confirm it lists the full variable set: `hostname, vmid, mac, ip, kind,
   os, domain_join, cephfs_mounts, rbd_disk, extra_packages, static_ip,
   static_gw, ad_domain, ad_realm, state_log_path`
3. Confirm it describes how to add a new extension and states the "never
   mutates guest state" contract

## End-to-End Scenario: Full domain-joined kitchen-sink VM lifecycle

Purpose: validate that all optional flags interact correctly on a single VM
through create → verify → reconfigure → destroy.

| Step | Action | Expected |
|------|--------|----------|
| E.1 | `export AD_JOIN_PASSWORD=<real>` | — |
| E.2 | `uv run pmx new --name e2e-full-$$ --kind vm --os ubuntu --cephfs supernote:/mnt/sn --rbd-disk 10 --extra-packages htop,jq --static-ip 192.168.9.80/24` | Exit 0; state log appended |
| E.3 | `cat state/guests.jsonl \| tail -1 \| python3 -m json.tool` | All expected fields populated with correct types (vmid int, domain_joined bool, cephfs_mounts list) |
| E.4 | `uv run pmx verify e2e-full-$$` | Exit 0; three `[ OK ]` lines |
| E.5 | `ssh ansible@192.168.9.80 "findmnt /mnt/sn && which htop jq && ip -4 addr show \| grep 192.168.9.80/24 && id Administrator@broken.wrx && lsblk \| grep 10G"` | All succeed |
| E.6 | `uv run pmx reconfigure e2e-full-$$` (twice) | Both exits 0; second ansible recap shows `changed=0` |
| E.7 | `ssh root@192.168.9.12 "qm reboot <vmid>"`; wait 60s | `findmnt /mnt/sn` still shows ceph mount after reboot (AC8.1) |
| E.8 | `uv run pmx destroy e2e-full-$$ --yes` | Exit 0; `qm list` no longer contains hostname |

## AC Traceability

| AC | Automated | Manual | Notes |
|----|-----------|--------|-------|
| AC1.1 | test_create_vm.sh, test_ad_join.sh | — | integration harness |
| AC1.2 | test_ad_join.sh | — | integration harness |
| AC1.3 | test_ad_join.sh (partial) | Phase 3 AC1.3 | hybrid |
| AC1.4 | tests/unit/test_preflight.py | — | Unit verified |
| AC1.5 | test_ad_join.sh (weak) | Phase 3 AC1.5 | hybrid |
| AC2.1 | test_create_lxc.sh | — | integration harness |
| AC2.2 | test_ad_join.sh | — | integration harness |
| AC2.3 | test_kitchen_sink.sh | — | integration harness |
| AC2.4 | — | Phase 3 AC2.4 | human-only |
| AC3.1 | — | Phase 3 AC3.1 | human-only |
| AC3.2 | test_ad_join.sh (implicit via env var) | — | integration harness |
| AC3.3 | — | Phase 3 AC3.3 | human-only |
| AC4.1 | test_create_vm.sh, test_create_lxc.sh, test_ad_join.sh | — | integration harness |
| AC4.2 | same three | — | integration harness |
| AC4.3 | test_lifecycle.sh + tests/unit/test_verify.py | — | Unit + integration |
| AC5.1 | molecule verify.yml (both OS) | Phase 3 AC1.3 | hybrid |
| AC5.2 | molecule + test_ad_join.sh | — | integration harness |
| AC6.1 / 6.2 / 6.3 | — | Phase 1 | human-only by design |
| AC7.1 | molecule both OS + test_ad_join.sh | — | integration harness |
| AC7.2 | molecule + test_ad_join.sh | Phase 3 AC1.3 | hybrid |
| AC7.3 | ubuntu molecule | Phase 3 AC7.3 | hybrid |
| AC8.1 | test_kitchen_sink.sh | Phase 3 AC8.1 (reboot) | hybrid |
| AC8.2 | test_kitchen_sink.sh | — | integration harness |
| AC8.3 | module contract | Phase 3 AC8.3 | hybrid |
| AC8.4 | — | Phase 3 AC8.4 | human-only |
| AC9.1 | test_kitchen_sink.sh | — | integration harness |
| AC9.2 | tests/test_cli.py::test_rbd_disk_rejects_lxc | — | Unit verified |
| AC10.1 | test_kitchen_sink.sh | — | integration harness |
| AC10.2 | — | Phase 3 AC10.2 | human-only |
| AC11.1 | test_kitchen_sink.sh | — | integration harness |
| AC11.2 | test_kitchen_sink.sh | — | integration harness |
| AC11.3 | test_create_vm.sh, test_create_lxc.sh | — | integration harness |
| AC12.1 / 12.2 / 12.3 | test_lifecycle.sh | — | integration harness |
| AC13.1 | test_lifecycle.sh | — | integration harness |
| AC13.2 | test_lifecycle.sh (exit 0 only) | Phase 3 AC13.2 | hybrid |
| AC13.3 | — | Phase 3 AC13.3 | human-only |
| AC14.1 | tests/unit/test_verify.py + test_lifecycle.sh | — | Unit + integration |
| AC14.2 | tests/unit/test_verify.py | — | Unit verified |
| AC14.3 | tests/unit/test_verify.py | — | Unit verified |
| AC15.1 / 15.2 / 15.3 | test_state_log.sh | — | integration harness |
| AC16.1 / 16.2 | test_state_log.sh | — | integration harness |
| AC16.3 | file exists at `docs/extending-post-create.md` | Phase 3 AC16.3 | human-only for content review |
