# Stage 0 status — PVE 9.2 + Ceph Tentacle upgrade

Living status for the Stage 0 gates in
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).

- **First assessed:** 2026-09-05 (read-only)
- **Last updated:** 2026-09-06 01:30, after the execution pass
- **STATUS: Stage 0 COMPLETE — all gates closed. Stage A is unblocked.**

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
- **Console fallback.** Covered by a JetKVM, already tested against these
  machines (confirmed 2026-09-05). One portable IP-KVM for four nodes, so
  Stage C goes one node at a time with the device moved to the node being
  upgraded.
- **`reliant` decommission leftovers.** Fully cleaned — see below.
- **discovery's search domain.** Fixed — see below.

### Backups — all seven checklist items done

Full first run completed 2026-09-06 01:04. All seven guests plus all four node
configs are in PBS; **88.8 GiB stored of the 245 GiB quota (36%)**.

| VM | Zero data | Duration |
|---|---|---|
| 113 bifrost | 93% | 7m 13s |
| 9001 | 85% | 2m 00s |
| 101 hydrae | 72% | 37m 50s |
| 112 neptune | 51% | 1h 34m |
| 9000 | 36% | 7s |
| 100 galactica | 15% | 2h 15m |
| 105 tauron2 | 5% | 2h 09m |

The zero-data column is the trim (item 3) paying off: 113 pushed a 128 GiB
disk in seven minutes at 304 MiB/s because almost all of it read as zero.

- **Item 3, discard/fstrim.** Done on 100, 101, 112, 113. Allocation across the
  set fell 216 → 146 GiB. Wildly uneven, and worth understanding why: 101 gave
  back 44 GiB because its LV spans nearly the whole disk; 100 gave back only 9
  because ~35 GiB sits in unallocated LVM extents `fstrim` cannot reach; 112
  gave back 1 because it is genuinely close to full.
- **Item 4, job.** `pbs-nightly` created and **enabled**: 02:00,
  `keep-last=3,keep-weekly=4`, guests 100,101,105,112,113,9000,9001. Dirty
  bitmaps were established by the first run, so subsequent runs are incremental.
- **Item 5, first manual run.** Measured on template 9000: 23 MiB/s. The
  sustained figure across the real run was ~8-29 MiB/s per stream with the WAN
  uplink saturating at **~23 MiB/s aggregate** — running three nodes in
  parallel splits that pipe rather than multiplying it.
- **Item 6, node configs.** `etc.pxar` + `pve.pxar` in PBS for all four nodes.
  `/etc/pve` is correctly captured as its own archive (pxar skips it as a mount
  point inside `/etc`). **Re-run immediately before Stage C on each node.**
- **Item 7, test-restore — PASSED, gate closed.** Restored 113 to a fresh VMID
  9113 on kelvin (`--unique 1` to regenerate the MAC, plus `link_down=1`),
  booted it, and confirmed from inside: hostname `bifrost`, Ubuntu 24.04.4 LTS,
  `uptime 0 min`, `/` at 9.4 GiB used matching the source exactly. Then
  destroyed with `--purge`; no RBD image left behind and the live 113 was
  unaffected throughout.

  **Why this test was the one that mattered:** PBS verification checksums
  chunks *server-side and never decrypts*. With client-side encryption, a
  restore using our own keyfile is the only thing that proves the key actually
  recovers data. `pbs-restore` ran with
  `--keyfile /etc/pve/priv/storage/Cloud-PBS.com.enc` and produced a bootable
  guest, so the key and the paper key escrow are now proven rather than assumed.

### Still outstanding (not Stage 0 gates)

- **PBS verification of the stored backups.** Everything currently reads
  `UNVERIFIED`. A `verify_group` job on vm/105 was triggered via the API and
  was still running at 01:30 (~40 min for 64 GiB on shared hosted hardware).
  Our token holds `Datastore.Verify`, so this can be driven from any node:
  ```bash
  curl -sk -X POST -H "Authorization: PBSAPIToken=<tokenid>:<secret>" \
    -H 'Content-Type: application/json' -d '{"backup-type":"vm","backup-id":"105"}' \
    https://sh14-226.prod.cloud-pbs.com:8007/api2/json/admin/datastore/<ds>/verify
  ```
- **105's four snapshots are still present.** Deliberately held back until that
  verify finishes — do not destroy rollback points while the verification of
  their replacement is still in flight.

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

Stage 0 is closed. Before Stage A, apply the `pve8to9` remediations recorded in
the runbook (remove `systemd-boot`, fix the removable-bootloader debconf, add
`non-free-firmware` + `amd64-microcode`), one node at a time.
