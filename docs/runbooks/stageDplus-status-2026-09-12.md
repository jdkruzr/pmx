# Stage D+ status — CephX key rotation to `aes256k`

Started **2026-09-12 ~16:00 CDT**, immediately after Stage D.
**HEALTH_ERR cleared 16:20 CDT.** Remaining WRNs are all the guests-on-admin item (Stage E). Companion to
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

## The service-cipher question — resolved from source, then proven live

Read `src/auth/cephx/CephxKeyServer.cc` (tentacle branch). The session key a
client receives in a service ticket is typed as:

```cpp
int ktype = std::min<int>(key_type.value_or(info.service_secret.get_type()),
                          info.service_secret.get_type());
```

with the comment *"The session key cipher must be supported by both the
requesting client and the target service. During rolling upgrades, services are
typically upgraded before external clients."* So a client presenting an `aes`
key gets an `aes` session key **regardless of the rotating service key type**.
`auth_service_cipher` hardens only the mon-internal ticket encryption — which is
the actual CVE — and is designed to be safe for old clients. The CVE-2025-30156
page confirms kernel support "began in 7.0" (nodes) and is *recommended, not
required* for clients.

Applied 2026-09-12 ~16:20 CDT:

```bash
ceph mon set auth_service_cipher aes256k     # clears AUTH_INSECURE_SERVICE_TICKETS (the last ERR)
ceph mon set auth_preferred_cipher aes256k   # new keys default to aes256k
# auth_allowed_ciphers stays "aes, aes256k" — client.admin / guests are aes
```

**Proven, not assumed:** velorum (kernel 6.8.0-137) then did a *fresh* CephFS
mount with `client.admin` — new mon session, new service tickets under the
aes256k service cipher — and read 13 entries. Every existing guest mount
(neptune ×3, tauron ×2, pluto) stayed responsive.

## Result: `HEALTH_ERR` → `HEALTH_WARN`

| Check | State | Blocked on |
|---|---|---|
| `AUTH_INSECURE_SERVICE_KEY_TYPE` | **cleared** | — |
| `AUTH_INSECURE_SERVICE_TICKETS` | **cleared** | — |
| `AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE` | WRN | self-clears when the mon's rotating keys have all regenerated — **in practice two to three `auth_service_ticket_ttl` periods (it cleared between 17:19 and 18:49 CDT, not within one hour as first assumed)**. `ceph auth wipe-rotating-service-keys` forces it now but invalidates every client's tickets at once — safe per the `min()` logic, but a needless reconnect storm. Chose to wait. |
| `AUTH_INSECURE_CLIENT_KEY_TYPE` | WRN (1) | `client.admin` — the guests' key on 6.8 kernels |
| `AUTH_INSECURE_KEYS_ALLOWED` / `_CREATABLE` | WRN | `aes` must stay allowed while `client.admin` is `aes` |

The three remaining WRNs all trace to one fact: **guests use `client.admin` on
kernels without aes256k.** That is Stage E's "scope the admin key down" item,
and it is the same piece of work: give guests a dedicated CephFS-only key (on
`aes`, until their kernels catch up), move them off admin, rotate admin to
aes256k, and only then remove `aes` from `auth_allowed_ciphers`.

## False alarm worth recording

A `timeout 10 ls` on a neptune mount reported STALLED seconds after a failed
probe mount. A full sweep of every guest immediately after showed all mounts
responsive, and velorum/pluto's dmesg showed `mds0 reconnect success / recovery
completed` through the Stage D MDS failover. **6.8 kernel clients handled Stage
D correctly.** Lesson kept: verify *guest* mounts after any daemon roll, not just
the nodes'.
