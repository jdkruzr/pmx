# Test Requirements: pmx Provisioning

Generated from design acceptance criteria. Each AC maps to either an automated test (with location) or a documented human verification procedure.

## Automated Test Coverage

### pmx-provisioning.AC1: VM creation with AD join works end-to-end

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC1.1 | SSH-reachable within 120s | integration | `tests/integration/test_create_vm.sh` | Phase 3 Task 5; implicit via `wait_for_connection` in `common` plus post-run ssh check. Also re-exercised by `tests/integration/test_ad_join.sh` (Phase 5 Task 6). |
| AC1.2 | `id Administrator@broken.wrx` resolves | integration | `tests/integration/test_ad_join.sh` | Phase 5 Task 6; explicit `ssh ... id Administrator@broken.wrx`. |
| AC1.3 | Domain Admins SSH + sudo + auto `/home/<user>` | integration | `tests/integration/test_ad_join.sh` | Phase 5 Task 6; sudoers-drop-in visudo check + mkhomedir probe. See human verification for interactive login element. |
| AC1.4 | `pmx new --name <existing>` refuses | unit | `tests/unit/test_preflight.py` | Phase 3 Task 1; `_parse_names` + `assert_name_available` raises `click.Abort`. |
| AC1.5 | realm join failure leaves guest + surfaces vmid | integration | `tests/integration/test_ad_join.sh` | Phase 5 Task 6 AC3.3 block (wrong password produces non-zero exit with vmid in output); see human verification for failure-path inspection. |

### pmx-provisioning.AC2: Unprivileged LXC with UID-map fix

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC2.1 | Unprivileged + `/proc/self/uid_map` extended | integration | `tests/integration/test_create_lxc.sh` | Phase 4 Task 4; explicit `grep '500000000 500000000 99999999'` assertion. |
| AC2.2 | `id Administrator@broken.wrx` inside LXC | integration | `tests/integration/test_ad_join.sh` | Phase 5 Task 6; LXC variants run alongside VM. |
| AC2.3 | Ceph pass-through mount visible in LXC | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; `pct exec ${vmid} -- findmnt /mnt/sn`. |
| AC2.4 | idmap write failure bails before start | human | — | See human verification; simulated via read-only `/etc/pve/lxc/` or invalid idmap syntax. |

### pmx-provisioning.AC3: AD credential prompt and caching

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC3.1 | Fresh shell prompts once (hidden) | human | — | See human verification; cannot fully automate TTY + hidden input behavior. |
| AC3.2 | Same shell reuses `$AD_JOIN_PASSWORD` | integration | `tests/integration/test_ad_join.sh` | Phase 5 Task 6 AC3.2 block: `export AD_JOIN_PASSWORD=x; pmx new ... --dry-run` must not prompt. |
| AC3.3 | Wrong password does not poison cache | integration | `tests/integration/test_ad_join.sh` | Phase 5 Task 6 AC3.3 block. |

### pmx-provisioning.AC4: Ubuntu and Rocky both first-class

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC4.1 | `--os ubuntu` VM + LXC | integration | `tests/integration/test_create_vm.sh`, `tests/integration/test_create_lxc.sh`, `tests/integration/test_ad_join.sh` | Phase 3 Task 5 (VM non-domain), Phase 4 Task 4 (LXC non-domain), Phase 5 Task 6 (domain-joined). |
| AC4.2 | `--os rocky` VM + LXC | integration | `tests/integration/test_create_vm.sh`, `tests/integration/test_create_lxc.sh`, `tests/integration/test_ad_join.sh` | Same three harnesses, rocky OS. |
| AC4.3 | Both pass `pmx verify` | integration | `tests/integration/test_lifecycle.sh` | Phase 7 Task 5; see also unit coverage in `tests/unit/test_verify.py`. |

### pmx-provisioning.AC5: pam-auth-update mkhomedir default-on

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC5.1 | First login creates `/home/<user>` | integration + human | `ansible/roles/ad_join_ubuntu/molecule/default/verify.yml`, `ansible/roles/ad_join_rocky/molecule/default/verify.yml` | Phase 5 Task 4 molecule tests grep `pam_mkhomedir`/`pam_oddjob_mkhomedir`. Full live mkhomedir requires actual AD user ssh — see human verification. |
| AC5.2 | Consistent on Ubuntu + Rocky | integration | Same molecule tests (both platforms) + `tests/integration/test_ad_join.sh` | Phase 5 Task 4 + Task 6. |

### pmx-provisioning.AC6: pmx seed bootstrap

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC6.1 | Empty cluster produces 2 VM + 1 LXC templates | human | — | Phase 2 Task 6 documents as manual acceptance evidence; destructive to the lab cluster, no automated harness. |
| AC6.2 | Re-run is no-op | human | — | Phase 2 Task 6 AC6.2 procedure. |
| AC6.3 | Partial state completes only missing work | human | — | Phase 2 Task 6 AC6.3 procedure (destroy one template, re-run). |

### pmx-provisioning.AC7: Sudoers drop-in

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC7.1 | `/etc/sudoers.d/domain-admins` exists, 0440, `visudo -cf` | molecule + integration | `ansible/roles/ad_join_ubuntu/molecule/default/verify.yml`, `ansible/roles/ad_join_rocky/molecule/default/verify.yml`, `tests/integration/test_ad_join.sh` | Phase 5 Tasks 4 and 6; explicit `stat` + visudo assertions. |
| AC7.2 | domain_admins members can sudo | integration | `tests/integration/test_ad_join.sh` | Phase 5 Task 6; full live sudo requires interactive AD login — see human verification. |
| AC7.3 | `visudo -cf` failure rolls back | molecule | `ansible/roles/ad_join_ubuntu/molecule/default/verify.yml` | Phase 5 Task 4; Ansible `template` module's `validate:` clause provides the rollback behavior; molecule verifies the file is valid via `visudo -cf`. Failure-path requires injecting a bad template — see human verification. |

### pmx-provisioning.AC8: --cephfs mount option

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC8.1 | VM: ceph-common + fstab + mount + reboot-survive | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; `findmnt /mnt/sn | grep ceph`. Reboot-survive is fstab-implied; see human verification for explicit reboot test. |
| AC8.2 | LXC: host mount + `mp<N>:` pass-through, no ceph-common in container | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; `grep mp[0-9]+:.*mp=/mnt/sn /etc/pve/lxc/${vmid}.conf` + inside-container findmnt. |
| AC8.3 | Idempotent re-run on existing host mount | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; `ansible.posix.mount state=mounted` is idempotent by module contract — no explicit re-run assertion but implied by running the role twice with no changes. See human verification for a specific double-run check. |
| AC8.4 | Missing `/etc/ceph/cephfs.secret` fails with actionable error | human | — | `roles/mount_cephfs/tasks/vm.yml` has `stat` + `fail` branch; no automated failure-path test — see human verification. |

### pmx-provisioning.AC9: --rbd-disk option

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC9.1 | VM gets 50G RBD disk from pool `bwrx` | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; `qm config ${vmid} | grep -E '^scsi1:\s+bwrx:.+,size=10G'`. |
| AC9.2 | `--rbd-disk` + `--kind lxc` fails fast | unit | `tests/unit/test_cli.py` | Phase 6 Task 1; Click `CliRunner` invocation asserting exit 2 with "VM-only" in output. |

### pmx-provisioning.AC10: --extra-packages

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC10.1 | Packages install via apt (Ubuntu) and dnf (Rocky) | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; `which htop && which jq` on both a VM (apt) and LXC (dnf). |
| AC10.2 | Unknown package surfaces error with vmid context | human | — | `roles/extra_packages/tasks/main.yml` has explicit `fail` with vmid annotation; no automated failure-path test — see human verification. |

### pmx-provisioning.AC11: --static-ip (default DHCP)

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC11.1 | VM boots with specified static IP/CIDR | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; `ip -4 addr show | grep 'inet 192.168.9.80/24'`. |
| AC11.2 | LXC boots with specified static IP | integration | `tests/integration/test_kitchen_sink.sh` | Phase 6 Task 5; same assertion plus `ip -4 route show default | grep 192.168.9.1` for inferred gateway. |
| AC11.3 | Absence of flag keeps DHCP | integration | `tests/integration/test_create_vm.sh`, `tests/integration/test_create_lxc.sh` | Phase 3/4 default path (no `--static-ip`); guest gets a DHCP lease and is reachable. |

### pmx-provisioning.AC12: pmx destroy

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC12.1 | Confirm + adcli + qm/pct destroy | integration | `tests/integration/test_lifecycle.sh` | Phase 7 Task 5; `pmx destroy ${NAME} --yes` followed by `qm list` absence check. |
| AC12.2 | `--no-domain` skips adcli with warning | integration | `tests/integration/test_lifecycle.sh` | Phase 7 Task 5; explicit `grep "skipping AD computer object cleanup"` on destroy log. |
| AC12.3 | Guest not in state log destroys with warning | integration | `tests/integration/test_lifecycle.sh` | Phase 7 Task 5 ORPHAN block; builds an LXC manually via `pct create`, then `pmx destroy` and greps for `"not in"`. |

### pmx-provisioning.AC13: pmx reconfigure

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC13.1 | Re-runs configure phase on existing guest | integration | `tests/integration/test_lifecycle.sh` | Phase 7 Task 5; `pmx reconfigure ${NAME}` exits 0. |
| AC13.2 | Second consecutive reconfigure is a no-op | integration | `tests/integration/test_lifecycle.sh` | Phase 7 Task 5; second invocation must also exit 0 with zero changes (implied; see human verification for explicit changed-count check). |
| AC13.3 | Reconfigure completes previously-failed AD join | human | — | Requires simulating a mid-configure failure (e.g. break DNS mid-run) — see human verification. |

### pmx-provisioning.AC14: pmx verify smoke test

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC14.1 | Healthy domain-joined guest returns 0 | integration + unit | `tests/integration/test_lifecycle.sh`, `tests/unit/test_verify.py` | Phase 7 Tasks 4–5; unit mocks all three `subprocess.run` calls succeeding. |
| AC14.2 | Stopped sssd returns non-zero with "sssd not active" | unit | `tests/unit/test_verify.py` | Phase 7 Task 4; mock `systemctl is-active sssd` non-zero, assert exit 1 + "sssd not active (AC14.2)" in stderr. |
| AC14.3 | Unresolvable Administrator@broken.wrx returns non-zero | unit | `tests/unit/test_verify.py` | Phase 7 Task 4; analogous mock for the `id` call. |

### pmx-provisioning.AC15: State log (DHCP seam)

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC15.1 | Build appends one JSON line with full field set | integration | `tests/integration/test_state_log.sh` | Phase 8 Task 3; Python inline asserts expected field set on first record. |
| AC15.2 | Log is append-only; prior entries preserved | integration | `tests/integration/test_state_log.sh` | Phase 8 Task 3; second build check + `grep` for both hostnames. |
| AC15.3 | Missing log file is created on first build | integration | `tests/integration/test_state_log.sh` | Phase 8 Task 3; `rm -f ${LOG}` before the first `pmx new`, then `test -f ${LOG}`. |

### pmx-provisioning.AC16: Post-create hook contract

| Criterion | Case | Test Type | Test Location | Notes |
| --------- | ---- | --------- | ------------- | ----- |
| AC16.1 | `post_create_hook` receives full variable set | integration | `tests/integration/test_state_log.sh` | Phase 8 Task 3; expected field set assertion implicitly proves the role got the vars. |
| AC16.2 | Default implementation writes state log only | integration | `tests/integration/test_state_log.sh` | Phase 8 Task 3; only side-effect is `state/guests.jsonl` append — no other artifacts produced. |
| AC16.3 | `docs/extending-post-create.md` exists | human | — | Documentation artifact; see human verification. |

### Supporting unit tests (not AC-mapped but cited by phase plans)

| File | Phase | Purpose |
| ---- | ----- | ------- |
| `tests/unit/test_preflight.py` | Phase 3 Task 1 | name-uniqueness parsing + `click.Abort` path |
| `tests/unit/test_cli.py` | Phase 6 Task 1 | `--rbd-disk + --kind lxc` rejection |
| `tests/unit/test_state.py` | Phase 7 Task 1 | JSONL read/find/append round-trips |
| `tests/unit/test_verify.py` | Phase 7 Task 4 | mocked smoke-test check ordering |

## Human Verification

### pmx-provisioning.AC1.3: Live SSH + sudo by a Domain Admins member
- **Why human:** Requires a real AD user session with credentials the test harness cannot supply (no passwordless key to an AD-user homedir until `mkhomedir` runs at least once).
- **Procedure:** After `pmx new --name foo --os ubuntu`, from a workstation with AD-user Kerberos ticket or interactively: `ssh someuser@broken.wrx@<ip>`; expect auto-created `/home/someuser@broken.wrx` (or `/home/someuser_broken.wrx` due to `override_space`) and ability to run `sudo -i`.

### pmx-provisioning.AC1.5: realm-join failure surfaces vmid for recovery
- **Why human:** Simulating a mid-configure AD outage in an automated test would poison the lab domain controller; safer to inspect the error path manually.
- **Procedure:** Break DNS or stop the Zentyal Samba AD service; run `pmx new --name foo --os ubuntu`; expect the CLI to exit non-zero with vmid printed in the error and the guest still running (verify via `qm list`). Then `pmx reconfigure foo` to resume once AD is healthy.

### pmx-provisioning.AC2.4: idmap write failure bails before start
- **Why human:** The failure mode is filesystem-level (e.g. read-only `/etc/pve/lxc/`), which the integration harness doesn't set up; noted as optional in Phase 4 Task 4.
- **Procedure:** Temporarily `chattr +i /etc/pve/lxc/<new_vmid>.conf` or introduce an invalid idmap syntax in `lxc_idmap_block`; run `pmx new --kind lxc`; expect the blockinfile task to fail before `pct start` runs; verify `pct status <vmid>` reports "stopped" or the VMID was never created.

### pmx-provisioning.AC3.1: Fresh shell prompts once with hidden input
- **Why human:** Getpass behavior requires a real TTY; CI stdin-only simulation doesn't verify echo-off.
- **Procedure:** Open a fresh shell, `unset AD_JOIN_PASSWORD`, run `pmx new --name foo --kind vm --os ubuntu --dry-run`; observe that "AD join password (jtd@broken.wrx): " prints, input is hidden (no echo), and the CLI proceeds after any input.

### pmx-provisioning.AC5.1: First login creates /home/<user> for a real AD user
- **Why human:** Requires a real AD-user ssh session; molecule grep only proves `pam_mkhomedir`/`pam_oddjob_mkhomedir` is wired, not that the session hook fires.
- **Procedure:** After a domain-joined build, `ssh someuser@broken.wrx@<ip>`; on first login verify `/home/someuser_broken.wrx` is created with correct ownership (`stat -c '%U %G' /home/someuser_broken.wrx`).

### pmx-provisioning.AC6.1 / AC6.2 / AC6.3: pmx seed bootstrap
- **Why human:** Phase 2 Task 6 explicitly documents these as "manual integration check, not an automated test" — destructive to the lab cluster, no CI harness.
- **Procedure:**
  - AC6.1: `ssh root@192.168.9.12 "qm destroy 9000 --purge; qm destroy 9001 --purge"`, then `pmx seed`; verify both templates plus `pveam list cephfs | grep rockylinux-9`.
  - AC6.2: `pmx seed` again; expect `changed=0` across all three roles.
  - AC6.3: destroy only VMID 9001, re-run `pmx seed`; expect only the Rocky role to do work.

### pmx-provisioning.AC7.2: Real AD user can sudo without backslash-space parse errors
- **Why human:** Requires an interactive sudo attempt as a real AD user.
- **Procedure:** As an AD-user SSH session on a provisioned guest, run `sudo -n true` (or `sudo -l`); expect no parse errors and either success or a password prompt.

### pmx-provisioning.AC7.3: visudo -cf failure rolls back the sudoers drop-in
- **Why human:** Requires injecting a deliberately bad sudoers template; not part of the default role path.
- **Procedure:** Temporarily edit `roles/ad_join_common/templates/sudoers-domain-admins.j2` to contain invalid syntax (e.g. `BOGUS domain_admins ALL=ALL`); run `pmx new`; expect the template task to fail during `validate:` and `/etc/sudoers.d/domain-admins` to remain at its prior content (or absent on first run). Ansible's `template validate:` implements this rollback.

### pmx-provisioning.AC8.1: Reboot-survival of the VM CephFS mount
- **Why human:** Integration harness mounts and checks live, but does not reboot the VM.
- **Procedure:** After `tests/integration/test_kitchen_sink.sh` builds the VM, `ssh root@192.168.9.12 "qm reboot <vmid>"`; wait 60s; `ssh ansible@<ip> "findmnt /mnt/sn"`; expect the mount to be present (fstab entry replayed at boot).

### pmx-provisioning.AC8.3: Explicit idempotent re-run of mount_cephfs
- **Why human:** Phase 6 Task 5 asserts live mount but does not run the role twice with a changed-count check.
- **Procedure:** After a successful `--cephfs` build, re-run `pmx reconfigure <name>`; inspect ansible output for `changed=0` on every mount_cephfs task.

### pmx-provisioning.AC8.4: Missing cephfs.secret produces actionable error
- **Why human:** Requires temporarily moving the workstation secret; destructive if done during other concurrent runs.
- **Procedure:** `sudo mv /etc/ceph/cephfs.secret /etc/ceph/cephfs.secret.bak`; run `pmx new --cephfs supernote:/mnt/sn ...`; expect the `vm.yml` `stat`+`fail` branch to print "pmx requires /etc/ceph/cephfs.secret on the workstation..."; restore the file.

### pmx-provisioning.AC10.2: Unknown package produces vmid-annotated error
- **Why human:** Requires injecting an intentionally bad package name; not worth a permanent harness.
- **Procedure:** `pmx new --name pkgfail-test --extra-packages definitely-not-a-real-package-xyz ...`; expect non-zero exit and the error to include the guest's VMID per `roles/extra_packages/tasks/main.yml` fail message.

### pmx-provisioning.AC13.2: Second reconfigure reports zero changes
- **Why human:** `tests/integration/test_lifecycle.sh` runs `pmx reconfigure` twice but only asserts exit 0 — it does not parse changed-count.
- **Procedure:** After the second `pmx reconfigure <name>` in the lifecycle harness, inspect the ansible recap line manually; expect `changed=0 failed=0` across all hosts.

### pmx-provisioning.AC13.3: Reconfigure recovers from previously-failed configure
- **Why human:** Requires deliberately failing the first configure run (e.g., stop Zentyal mid-realm-join), then verifying reconfigure resumes.
- **Procedure:** Start `pmx new --name recov-test --os ubuntu`; while `realm join` is running, `systemctl stop samba-ad-dc` on Zentyal; wait for the CLI to fail with a vmid. Restore Zentyal, run `pmx reconfigure recov-test`; expect exit 0 and `realm list` to now show the domain.

### pmx-provisioning.AC16.3: docs/extending-post-create.md exists and documents the contract
- **Why human:** Documentation review is inherently subjective — a presence check via `test -f` would be trivial but doesn't verify usefulness.
- **Procedure:** Open `docs/extending-post-create.md`; confirm it lists the full variable table (hostname, vmid, mac, ip, kind, os, domain_join, cephfs_mounts, rbd_disk, extra_packages, static_ip, static_gw, ad_domain, ad_realm, state_log_path), describes how to add a new extension, and states the "never mutates guest state" contract.

## Coverage Gaps

(none — all 16 ACs and their sub-items have either an automated test file cited in an implementation phase or a documented human verification procedure)
