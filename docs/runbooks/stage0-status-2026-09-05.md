# Stage 0 status — checked 2026-09-05

Read-only assessment of the Stage 0 gates in
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md). Nothing was
changed on the cluster. Checked from the laptop via SSH to `root@192.168.9.12`
(cerritos), fanning out to the other nodes over the cluster's own SSH.

## Cluster baseline (unchanged from runbook)

| Item | Value |
|---|---|
| PVE | pve-manager 8.2.4, kernel 6.8.12-1-pve |
| Ceph | 18.2.2 Reef on all 15 daemons (4 MON, 1 MGR, 2 MDS, 8 OSD) |
| Quorum | 4/4 nodes, quorate |
| Health | `HEALTH_OK`, 97/97 PGs active+clean, 3.6 TiB used / 15 TiB |
| MDS | 1 active, 2 standby |
| Guests | 14 VMs, 0 LXC; templates 9000/9001 on cerritos |

Guest placement: discovery 100, 103 · cerritos 101, 112, 113, 9000, 9001 ·
excelsior 104, 105, 110 · kelvin 106, 111, 115.

## Gate scorecard

### Done

- **Backups item 1, encryption.** `Cloud-PBS.com` storage has the encryption
  key set; fingerprint `82:81:ff:06:e4:7e:21:6e:...` matches
  `/etc/pve/priv/storage/Cloud-PBS.com.enc` (Sep 5) and the laptop copy in
  `~/pbs-keys/` (key + paper key). PBS reachable, 0.10% used of ~245 GiB.
- **Backups item 2, guest agent.** `qm agent <id> ping` OK on 100, 101, 105,
  112, 113. No pending config on any of them.
- **Sysctl.** All four nodes keep settings in `/etc/sysctl.d/`
  (`30-ceph-osd.conf`, `99-sysctl.conf`). Verify-only item, verified.
- **NIC names.** Plain `enp*` on every node, one active uplink each, no bonds.
  Relevant to Stage A pinning; nothing surprising.
- **Laptop SSH.** Passwordless to discovery (.11), cerritos (.12),
  excelsior (.13).
- **Repo clone on the laptop.** This one.

### Not done

- **Backups item 3 (optional), discard/fstrim.** None of the five disks has
  `discard=on`. VM 100 has `fstrim_cloned_disks=1` on the agent line, which is
  unrelated.
- **Backups item 4, job.** No backup jobs exist (`pvesh get /cluster/backup`
  returns `[]`).
- **Backups item 5, first manual run.** PBS holds zero backups.
- **Backups item 6, node `/etc` + `/etc/pve` to PBS.** Not done.
- **Backups item 7, test-restore.** Not done. **This is the gate-closer.**
- **Baseline capture.** No `pveversion -v` / `ceph versions` / `ceph osd
  dump` / `ceph auth ls` / `ip -br link` snapshots exist on any node or in
  the repo.
- **Laptop SSH to kelvin (.14).** Fails host-key verification in batch mode;
  one interactive `ssh root@192.168.9.14` to accept the key fixes it.
- **Console fallback.** Not checkable remotely. Confirm crash-cart access to
  all four nodes before Stage C.

## The `.10` MON anomaly — resolved (diagnosis only, not yet cleaned up)

`192.168.9.10` is `reliant.broken.wrx` per DNS: a former cluster node, now
gone. It does not answer ping, ARP is `INCOMPLETE`, it is not in
`corosync.conf`, not in the CRUSH map, and the monmap (epoch 6) has exactly
four MONs with `removed_ranks: {0}` — so it was removed properly. What it left
behind in `/etc/pve/ceph.conf` and the auth DB:

1. `mon_host = 192.168.9.10 192.168.9.11 192.168.9.14 192.168.9.13 192.168.9.12`
   — `.10` listed **first**. This is why every node's CephFS mount string
   carries five addresses; kernel clients try `.10` first and wait for a
   timeout. Directly relevant to `cephfs-client-wedged.md`.
2. A stale `[mon.reliant]` / `public_addr = 192.168.9.10` section.
3. A leftover `mgr.reliant` entity in `ceph auth ls`.
4. Bonus: `public_network` and `cluster_network` are written as
   `192.168.9.10/24` rather than `192.168.9.0/24`. Functionally identical, but
   worth normalising so `pve8to9` and future readers don't blink at it.

### Proposed cleanup (small, do before Stage A)

```bash
# on any node; /etc/pve/ceph.conf is cluster-wide
sed -i \
  -e 's/^\tmon_host = .*/\tmon_host = 192.168.9.11 192.168.9.12 192.168.9.13 192.168.9.14/' \
  -e 's#192.168.9.10/24#192.168.9.0/24#' \
  /etc/pve/ceph.conf
# delete the [mon.reliant] block (two lines + blank) by hand or with sed
ceph auth del mgr.reliant
# verify
ceph mon dump | grep -c '^[0-9]:'    # expect 4
ceph -s                              # still HEALTH_OK
```

Existing CephFS mounts keep the old five-address string until remounted; the
Stage C reboots take care of that. No need to remount now.

## Suggested order from here

1. Accept kelvin's host key from the laptop.
2. Clean up the reliant leftovers (above).
3. Baseline capture on all four nodes (stash under `/root/upgrade-baseline/`
   and copy to the laptop).
4. Backup checklist items 4 → 7, ending with the test-restore that closes the
   gate.
5. Confirm crash-cart access. Then Stage A.
