# Stage D status — Ceph Squid → Tentacle

Completed **2026-09-12 ~15:40 CDT**, same afternoon as Stage C. Companion to
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).

**Result: all 18 daemons on Ceph 20.2.4 Tentacle (`-pve4`, the August CVE
build), `min_mon_release 20`, `require_osd_release tentacle`, 97 PGs
active+clean, CephFS read+write on all four nodes, 13 client sessions open.**

## What differed from the runbook, in our favour

- **20.2.4-pve4 had reached `no-subscription`.** The runbook expected 20.2.2 with
  the CVE build `test`-only; that was true at the last refresh and false by
  execution day. We got CVE-2025-30156's fix directly. This also satisfies
  Stage D+'s "≥ 20.2.4" gate, so the key rotation is unblocked node-side.
- The MDS "dance" was a no-op again — `max_mds=1`, no standby-replay.

## Sequence (one gated chain from kelvin)

| Step | Result |
|---|---|
| Binary install, all 4 nodes | 22 up / 2 new / **0 removed** each; rc=0 in 35–39 s; daemons kept running on 19.2.6 |
| MONs, one at a time | each rejoined quorum in 3–6 s → `min_mon_release 20 (tentacle)` |
| MGRs, standbys then active | active stayed on kelvin throughout |
| OSDs, node by node | **gate = 8 up AND all `active+clean`** (the Stage B fix) — passed in ~30 s per node, every time |
| MDS, standbys then active | active moved kelvin → discovery on the final restart; 13/13 sessions `open` |
| Finalize | `require-osd-release tentacle`, `noout` unset |

## Things to know

- **PVE 9 recreates `pve-enterprise.sources`.** Stage C deleted the PVE 8
  `pve-enterprise.list`; the 9.2 `pve-manager` postinst wrote a deb822
  `pve-enterprise.sources` in its place, and every `apt update` then logged two
  `401 Unauthorized` errors per node. Harmless (other repos fetched fine) but
  noisy and it trips health checks. Fixed with **`Enabled: false`** in the file
  on all four nodes — deleting it just invites the postinst to recreate it.
- The 20.2.4-pve4 version string reads `tentacle (stable - None)`. The "None" is
  a packaging artifact, not a fault.
- A mid-chain `ceph versions` sample showed "2 mgr on 19.2.6" seconds after the
  standby restarts — timing, not a failure. Final tally 18/18 on 20.2.4.

## Decision recorded: `HEALTH_ERR` stays visible

The six CephX "insecure key types" checks (two `ERR`, four `WRN`) persist
through Stage D — they're about key *types* and Tentacle doesn't change the keys.
Operator decision 2026-09-12: **do not mute.** The cause is known and the
behaviour is expected; it clears when Stage D+ rotates keys to `aes256k`. No
gate in this runbook depends on `HEALTH_OK`; they're all PG-state based.

## Next

- **Stage D+** — CephX rotation to `aes256k`. Node-side prerequisites are now
  met (20.2.4 everywhere, kernel 7.0 everywhere). Guest-side is not: pmx's
  `mount_cephfs` hands guests the **admin** key (one of the eight flagged client
  entities), and Rocky 9 / Ubuntu 24.04 guest kernels lack `aes256k`. Inventory
  guest CephFS mounts first; rotate node keys; leave guest keys until their
  kernels catch up.
- **Stage E** — reconcile pmx: `rpm-reef` → `rpm-tentacle` in `mount_cephfs`,
  scope the admin key down (ties directly into D+), `discard=on` at provision,
  re-validate CLI parsing on 9.2, run the integration smoke tests.
