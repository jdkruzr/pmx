# Stage B status — Ceph Reef → Squid

Completed **2026-09-09 ~03:10 CDT**. Companion to
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).
Stage A finished 2026-09-07 (see [`stageA-status-2026-09-06.md`](stageA-status-2026-09-06.md)).

**Result: all 18 daemons on Ceph 19.2.5 Squid, `HEALTH_OK`, and `pve8to9 --full`
is down to 0 FAILURES. Stage C is unblocked.**

## Pre-flight findings that simplified the work

- `ceph-squid bookworm no-subscription` exists and offers **19.2.5-1~bpo12+2**.
- **`max_mds` was already 1** and **`allow_standby_replay` was not set**
  (`flags 12 joinable allow_snaps allow_multimds_snaps`), so the runbook's MDS
  rank-reduction dance was a **no-op**. The MDS step reduced to: restart the two
  standbys, then restart the active and let it fail over.
- 13 CephFS client sessions were connected throughout — the population most at
  risk from an MDS failover (see [`cephfs-client-wedged.md`](cephfs-client-wedged.md)).

## What was done

1. **Repo switch on all four nodes**, `ceph-reef` → `ceph-squid`, then
   `apt full-upgrade`. rc=0 everywhere; **binaries went to 19.2.5 while running
   daemons stayed on 18.2.8**, which is the intended intermediate state.
2. `ceph osd set noout`.
3. **MONs**, one node at a time — each rejoined quorum in **~3 s**. After all
   four: `min_mon_release 19 (squid)`.
4. **MGRs** — standbys first, then the active. The active mgr never dropped.
5. **OSDs**, node by node.
6. **MDS** — standbys (discovery, cerritos) first, then the active on kelvin.
   Failover to cerritos took **~3 s**.
7. `ceph osd require-osd-release squid`, then `ceph osd unset noout`.

Ceph itself prompts for step 7 once the OSDs are done, via
`[WRN] OSD_UPGRADE_FINISHED: all OSDs are running squid or later but
require_osd_release < squid`.

## Mistake worth not repeating

The OSD roll-out script gated on "all 8 OSDs up **and** no
`peering|down|stale|inactive|incomplete` PGs" — it **did not check for
`undersized|degraded`**. So it advanced to the next node while the previous
node's PGs were still **28.97%, 11.0% and 19.1% degraded**.

The runbook says wait for `active+clean`, and that gate did not enforce it. With
`size=3`/`min_size=2`, taking a second node's OSDs down while a large fraction
of PGs are already at 2 copies can drop some to 1 copy and stall client I/O. It
did not happen here — no PG ever reached `inactive` or `incomplete`, because OSD
restarts are quick and recovery kept pace — but that was margin, not design.

**Correct gate for Stage C and any future roll:**

```bash
until ceph pg stat | grep -qvE 'degraded|undersized|recovering|backfill|peering'; do sleep 10; done
```

or simply require `ceph pg stat` to report only `active+clean` (plus scrubbing)
before touching the next node.

## Verification

- **All 18 daemons on 19.2.5**: 4 mon, 3 mgr, 8 osd, 3 mds.
- `min_mon_release 19 (squid)`, `require_osd_release squid`.
- `HEALTH_OK`, 97 PGs active+clean.
- **CephFS proven functional, not merely "up"** — each node's `/mnt/pve/cephfs`
  was read *and* write tested rather than trusting the MDS status line:
  ```bash
  ls /mnt/pve/cephfs && touch /mnt/pve/cephfs/.probe && rm /mnt/pve/cephfs/.probe
  ```
  All four passed. All **13 MDS client sessions in state `open`** — none stale,
  reconnecting, or being killed. No wedge.
- `pve8to9 --full`: **56 checks, 50 PASS, 4 SKIP, 2 WARN, 0 FAIL.** The two
  warnings are expected — `noout` not set (only wanted *during* an upgrade) and
  running guests.

## Next

Stage C — PVE 8 → 9.2, Bookworm → Trixie, kernel 7.0. This is the genuinely
risky stage: an OS major upgrade rather than a package-version roll. Carry
forward the Stage A techniques (boot_id reboot detection, deliberate mgr
failover, three-way NIC-pin verification, the kernel-pin check on every node)
**and the corrected PG gate above**.
