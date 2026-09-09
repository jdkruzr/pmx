# PBS backup reliability — hosted `Cloud-PBS.com`

Last verified: 2026-09-08

Companion to [`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).
These backups are the safety net for Stages B–D, so their failure modes matter.

## The problem

Scheduled nightly backups intermittently fail **one or two guests per run**:

```
ERROR: backup finish failed: command error: stream closed because of a broken pipe
```

| Run (cluster time, CDT) | Failed |
|---|---|
| 09-07 02:00 | vm/101 (cerritos), vm/105 (excelsior) |
| 09-08 02:00 | vm/100 (discovery) |

What the evidence says:

- **Always in the `finish` phase**, never during data transfer.
- **Not bandwidth.** The failures happened on tiny incrementals — 924 MiB and
  1.3 GiB dirty — not on multi-GiB reads.
- **All nodes started within one second of each other** (02:00:00, 02:00:00,
  02:00:01), because a single cluster-wide vzdump job fires on every node at once.
- **Serialized manual re-runs succeeded 3 for 3** (vm/100, vm/101, vm/105), each
  in under a minute using dirty bitmaps.

Working hypothesis: **concurrent connections** from several nodes to the hosted
PBS, not throughput. Not proven — "02:00 is a bad time at the provider" fits the
same data — so the staggering below doubles as the experiment.

## Detecting an incomplete backup

A failed-finish snapshot still appears in the datastore **and still verifies
`ok`**, because the chunks that arrived are intact. The tell is the file list:

- **Complete VM backup:** `qemu-server.conf.blob`, `drive-*.img.fidx`,
  `index.json.blob`, **`client.log.blob`**
- **Failed finish:** the same minus `client.log.blob` (uploaded last)

```bash
curl -sk -H "Authorization: PBSAPIToken=<tokenid>:<secret>" \
  "https://<host>:8007/api2/json/admin/datastore/<ds>/snapshots"
# then check each snapshot's files[] for client.log.blob
```

**Do not apply this test to `host/*` backups.** `proxmox-backup-client` writes a
different file set — `etc.pxar.didx`, `pve.pxar.didx`, `catalog.pcat1.didx`,
`index.json.blob` — and never a `client.log.blob`. Judging those by the same
rule reports healthy backups as failed.

## Mitigation 1 — stagger the jobs (2026-09-08)

Replaced the single cluster-wide `pbs-nightly` with three jobs 30 minutes apart,
grouped so that (at current guest placement) only one node backs up at a time:

| Job | Schedule | Guests |
|---|---|---|
| `pbs-a-discovery` | 02:00 | 100 |
| `pbs-b-cerritos` | 02:30 | 101, 112, 113, 9000, 9001 |
| `pbs-c-excelsior` | 03:00 | 105 |

All keep `keep-last=3,keep-weekly=4`.

**Caveat:** the grouping is by *current* placement. Guests migrate, so this can
drift back toward partial concurrency — revisit after any lasting placement
change, and especially after Stage C.

## Mitigation 2 — verification jobs

The provider already runs `default-5i0tqrtf1tddhj1y2o` daily at **16:12**. That
is why snapshots show `verify=ok` without us doing anything, but it is ~14 hours
behind a 02:00 backup.

Added `daily-verify` at **04:00**, right after the backup window, with
`ignore-verified=true` and `outdated-after=7` so it only checks new or stale
snapshots:

```bash
curl -sk -X POST -H "Authorization: PBSAPIToken=<tokenid>:<secret>" \
  -H 'Content-Type: application/json' \
  -d '{"id":"daily-verify","store":"<ds>","schedule":"04:00","ignore-verified":true,"outdated-after":7}' \
  https://<host>:8007/api2/json/config/verify
```

Note that **verification does not decrypt**. It proves stored chunks are intact,
not that our key recovers them — only a restore with the keyfile does that (see
the Stage 0 test-restore).

## Recovery when a backup fails

Re-run just the affected guest. It is fast, because the dirty bitmap survives a
failed finish:

```bash
vzdump <vmid> --storage Cloud-PBS.com --mode snapshot
```

Observed: vm/100 924 MiB in 52 s, vm/101 1.12 GiB in 51 s, vm/105 676 MiB in 31 s.

Retention keeps the previous night's verified copy, so a single failed run never
leaves a guest without a good backup.

## Gotcha: timezones

The workstation is **EDT**; the cluster is **CDT**. PBS returns epoch times, so
rendering them in workstation-local time shifts every backup by an hour and makes
a 02:00 job look like it ran at 03:00. Render cluster timestamps in cluster time:

```bash
... | TZ=America/Chicago python3 -c '...'
```

## Retention — verified correct, not a problem

`keep-last=3` behaves exactly as configured; every group holds three snapshots.
An earlier reading of "only 2 copies" was a transient mid-cycle observation taken
before that night's run, not a policy fault. Confirmed with a dry run, which
changes nothing:

```bash
curl -sk -X POST -H "Authorization: PBSAPIToken=<tokenid>:<secret>" \
  -H 'Content-Type: application/json' \
  -d '{"backup-type":"vm","backup-id":"101","dry-run":true,"keep-last":3}' \
  https://<host>:8007/api2/json/admin/datastore/<ds>/prune
```
