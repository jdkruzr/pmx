# Stage 0 status — PVE 9.2 + Ceph Tentacle upgrade

Living status for the Stage 0 gates in
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).

- **First assessed:** 2026-09-05 (read-only)
- **Last updated:** 2026-09-05, after the first execution pass

Work is driven from the laptop over SSH to the four nodes.

## Cluster baseline

Captured pre-change and stored on each node at
`/root/upgrade-baseline/20260905/` (23 files each), mirrored to the laptop at
`~/upgrade-baseline/20260905/<node>/`. Contents: `pveversion -v`, `pvecm
status|nodes`, `ip -br link|addr`, `/etc/network/interfaces`, `ceph.conf`,
`corosync.conf`, `pvesm status`, `qm list`, `pct list`, `dpkg -l`, `uname -a`,
`/proc/mounts`, and the Ceph set (`versions`, `-s`, `osd dump`, `osd tree`,
`mon dump`, `df`, `fs dump`, `config dump`, `auth ls` with keys redacted).

| Item | Value |
|---|---|
| PVE | pve-manager 8.2.4 on all four nodes, kernel 6.8.12-1 |
| Ceph | 18.2.2 Reef on all 15 daemons (4 MON, 1 MGR, 2 MDS, 8 OSD) |
| Quorum | 4/4 nodes, quorate |
| Health | `HEALTH_OK`, 97/97 PGs active+clean, 3.6 TiB used / 15 TiB |
| Cluster name | `brokenworks` |
| Uplinks | one active NIC per node: `enp1s0f0` on discovery/cerritos/kelvin, `enp1s0` on excelsior |

`pve8to9` is not present on 8.2.4 (only `pve7to8`); it arrives with 8.4 in
Stage A, as the runbook assumes.

## Gate scorecard

### Done

- **Baseline capture.** All four nodes, pre-change, on-node + laptop copies.
- **Laptop SSH to all four nodes.** Batch-mode, passwordless, verified.
- **Inter-node SSH, full 4x4 mesh by short name.** Verified — this is what
  Stage C migrations need.
- **Backups item 1, encryption.** `Cloud-PBS.com` has the encryption key set;
  fingerprint `82:81:ff:06:...` matches `/etc/pve/priv/storage/Cloud-PBS.com.enc`
  and the laptop copy in `~/pbs-keys/` (key + paper key). PBS reachable,
  0.10% used of ~245 GiB.
- **Backups item 2, guest agent.** `qm agent <id> ping` OK on 100, 101, 105,
  112, 113. No pending config on any of them.
- **Sysctl.** Settings present in `/etc/sysctl.d/` on all four nodes.
- **NIC names.** Plain `enp*`, one active uplink each, no bonds. Recorded for
  the Stage A pinning step.
- **Console fallback.** Covered by a JetKVM (confirmed 2026-09-05). One
  portable IP-KVM for four nodes, so Stage C goes strictly one node at a time
  with the device attached to the node being upgraded.
- **`reliant` decommission leftovers.** Fully cleaned — see below.
- **discovery's search domain.** Fixed — see below.

### Not done

- **Backups item 3 (optional), discard/fstrim.** No disk has `discard=on`.
  VM 100's `fstrim_cloned_disks=1` is an unrelated agent setting.
- **Backups item 4, job.** No backup jobs (`pvesh get /cluster/backup` → `[]`).
- **Backups item 5, first manual run.** PBS holds zero backups.
- **Backups item 6, node `/etc` + `/etc/pve` to PBS.** Not done.
- **Backups item 7, test-restore.** Not done. **This is the gate-closer.**


### Corrected from the first pass

- The SSH failure was **excelsior (.13)**, not kelvin (.14). kelvin's keys were
  already present and correct; excelsior had no entry at all. Both verified
  against `/etc/pve/priv/known_hosts` and against the hosts' own
  `/etc/ssh/ssh_host_*.pub` fetched over the cluster's authenticated channel
  before being added to the laptop's `known_hosts`.

## The `reliant` decommission — cleaned up 2026-09-05

`192.168.9.10` was `reliant.broken.wrx`, a former cluster node. It was removed
properly (monmap epoch 6 has four MONs with `removed_ranks: {0}`, and corosync
lists only the four live nodes), but left six pieces of litter behind. All six
are now gone. Every change was backed up to `/root/*.bak-<timestamp>` on
cerritos first.

| # | Leftover | Action |
|---|---|---|
| 1 | `mon_host` listed `.10` **first**, so every CephFS mount string carried a dead address clients tried first | rewrote to `192.168.9.11 .12 .13 .14` |
| 2 | stale `[mon.reliant]` section in `ceph.conf` | removed |
| 3 | `public_network`/`cluster_network` written as `192.168.9.10/24` | normalised to `192.168.9.0/24` |
| 4 | orphaned `mgr.reliant` entity in the Ceph auth DB | `ceph auth del mgr.reliant` |
| 5 | `ReliantData` LVM storage pinned to `nodes reliant` (VG absent everywhere, referenced by no guest, job, or replication) | `pvesm remove ReliantData` |
| 6 | stale `/etc/pve/nodes/reliant/` (cert, key, `lrm_status`; `qemu-server/` and `lxc/` both empty) | removed, tarball kept |

Also pruned: reliant's entries in `/etc/pve/priv/known_hosts`, and its
`root@reliant` key in `/etc/pve/priv/authorized_keys` — a standing root
credential for a machine that no longer exists.

Verified after: `ceph.conf` identical on all four nodes (md5 `425f7ad0`),
`HEALTH_OK`, 4 MONs, all storages active, 4/4 quorate, no `reliant` string
anywhere in `/etc/pve`, and fresh SSH to every node still working.

Item 1 is the fix directly relevant to
[`cephfs-client-wedged.md`](cephfs-client-wedged.md). Existing kernel mounts
keep the old five-address string until remounted; the Stage C reboots handle
that. No need to remount now.

## discovery's search domain — fixed 2026-09-05

Found while testing the inter-node mesh. discovery had `search broken.works`
(and a matching `/etc/hosts` FQDN) where every other node — and the actual AD
domain — is `broken.wrx`. Consequence: from discovery, `cerritos`,
`excelsior` and `kelvin` were all **NXDOMAIN**; it could only resolve itself,
via its own `/etc/hosts`. That would have broken guest migration *off*
discovery during the Stage C rolling reboots.

Fixed with `pvesh set /nodes/discovery/dns --search broken.wrx`. All four names
now resolve from discovery and the full 4x4 short-name SSH mesh passes.

**Left alone deliberately:** discovery's `/etc/hosts` line still reads
`discovery.broken.works`, and its PVE cert CN is `discovery.broken.works`
(SAN also covers `discovery` and `192.168.9.11`). Correcting those means
reissuing the node certificate (`pvecm updatecerts -f` + `pveproxy` restart).
Not required for the upgrade; decide separately.

## Order from here

1. ~~Accept the missing host key~~ — done (it was excelsior).
2. ~~Clean up the reliant leftovers~~ — done.
3. ~~Baseline capture~~ — done.
4. Backup checklist items 4 → 7, ending with the test-restore that closes the
   gate. **This is the only remaining blocker.**
5. ~~Confirm crash-cart access~~ — done (JetKVM). Then Stage A.
