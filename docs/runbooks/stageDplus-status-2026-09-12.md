# Stage D+ status — CephX key rotation to `aes256k`

Started **2026-09-12 ~16:00 CDT**, immediately after Stage D. Companion to
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).

## Mechanism, as learned on this build (20.2.4-pve4) — no docs are shipped

- **Key type is encoded in the key blob**: base64-decode, first 2 bytes LE.
  `aes` = type **1** (16-byte secret, 28-byte blob); `aes256k` = type **2**
  (32-byte secret, 44-byte blob). `ceph auth get` does not expose it; decode it.
- **`ceph auth rotate <entity> --key_type aes256k` is immediate**, not pending.
  The health check lags by a few seconds.
- `get-or-create-pending` takes no `--key_type`; it uses the monmap's
  `auth_preferred_cipher` (currently `aes`).
- Cipher policy lives in the **monmap**, not `ceph config`:
  `auth_service_cipher`, `auth_allowed_ciphers`, `auth_preferred_cipher`, set
  with `ceph mon set <name> <value>`.
- Older `mount.ceph` (Ubuntu 24.04's) rejects an aes256k secret in userspace
  ("secret is not valid base64") — it validates blob length. That is not a
  kernel verdict.

## Procedure used for daemon keys (zero guest exposure)

Two phases, all inside the 1 h service-ticket TTL:

1. **Rotate + rewrite keyring**, per entity: `ceph auth export` the old key to
   `/root/dplus-backup-<date>/` (rollback via `ceph auth import`), `ceph auth
   rotate <e> --key_type aes256k`, then `sed` the new key into the daemon's
   keyring file and verify the file matches `ceph auth get-key`. Running
   daemons keep serving on their existing tickets.
2. **Restart roll** = the Stage D chain minus MONs: MGRs standbys→active, OSDs
   node-by-node on the `active+clean` gate, MDS standbys→active, then guest
   mount sweep. A daemon that fails to start here has a keyring problem.

Keyring locations: `/var/lib/ceph/{osd,mds,mgr}/ceph-<id>/keyring` (node-local);
`client.crash` in `/etc/pve/ceph/ceph.client.crash.keyring` (pmxcfs, then restart
`ceph-crash` on every node); `client.bootstrap-osd` in
`/var/lib/ceph/bootstrap-osd/ceph.keyring` on every node; the other
`bootstrap-*` entities have no keyring files anywhere and were simply rotated.

## Result so far

**21 of 22 entities on aes256k.** All 8 OSDs, 3 MDS, 3 MGR, 6 `bootstrap-*`,
`crash`. Every daemon restarted and authenticated on its new key; gates passed in
~25–30 s; all guest mounts responsive afterwards.

Remaining: `client.admin` (aes) — deliberately, because **all 9 guest CephFS
mounts use it** (neptune, tauron, velorum, pluto, ceres/globus, on Ubuntu 6.8.0
kernels) and their aes256k support is unverified.

Health went from `ERR ×2 / WRN ×4` to **`ERR ×1 / WRN ×4`**:

| Check | Now | Blocked on |
|---|---|---|
| `AUTH_INSECURE_SERVICE_KEY_TYPE` | **cleared** | — |
| `AUTH_INSECURE_SERVICE_TICKETS` | ERR | `auth_service_cipher aes` — see open question |
| `AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE` | WRN | same |
| `AUTH_INSECURE_CLIENT_KEY_TYPE` | WRN (1) | `client.admin` ← guests |
| `AUTH_INSECURE_KEYS_ALLOWED` / `_CREATABLE` | WRN | `aes` must stay allowed while any client is aes |

## Open question — do not flip blind

`ceph mon set auth_service_cipher aes256k` would clear the last ERR. It is
runtime and reversible. **But** it is not known whether it changes only the
mon-internal rotating keys (client-opaque, safe) or also the **session keys
handed to clients** — which would break every 6.8-kernel guest mount at its next
ticket rotation. Proving it empirically requires `wipe-rotating-service-keys`,
which invalidates every client's tickets at once, so there is no safe bounded
test. Resolve from the Ceph source / CVE-2025-30156 advisory before acting.

## False alarm worth recording

A `timeout 10 ls` on a neptune mount reported STALLED seconds after a failed
probe mount. A full sweep of every guest immediately after showed all mounts
responsive, and velorum/pluto's dmesg showed `mds0 reconnect success / recovery
completed` through the Stage D MDS failover. **6.8 kernel clients handled Stage
D correctly.** Lesson kept: verify *guest* mounts after any daemon roll, not just
the nodes'.
