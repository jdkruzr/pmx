# Stage E status — 2026-09-12

Reconcile `pmx` with the upgraded cluster, and retire `client.admin` from every
CephFS client and PVE storage. Companion to the runbook's Stage E section in
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md) and the design
plan that produced it.

## Why this was more than "switch the role to a scoped key"

Pre-flight on 2026-09-12 found:

- **Five hosts mount CephFS as `client.admin`** (`allow *` on mon/mgr/osd/mds):
  neptune, tauron, velorum, pluto and **ceres** — a physical box at
  192.168.9.199, not the guest `globus` as previously recorded. Globus has no
  CephFS mount at all (its `mnt-cephfs.mount` unit is static and has never run).
- **Every one of them, plus globus, had `ceph.client.admin.keyring` and
  `cephfs.secret` world-readable (0644) in `/etc/ceph`.** The keyring wasn't even
  used (mounts use `secretfile=`); it only existed to be stolen. Any local user
  or any compromised web app (Nextcloud on tauron, deluge on pluto) could read
  the cluster's root credential.
- **PVE's own storages authenticate as `client.admin` too.** `bwrx.keyring` and
  `cephfs.secret` under `/etc/pve/priv/ceph/` are byte-identical to the admin
  key, so every running VM holds it in memory through librbd. Rotating admin in
  place would have stalled every VM's disk at its next mon re-authentication.
- **`pmx` encoded the same practice**: `mount_cephfs` copied the *workstation's*
  `/etc/ceph/cephfs.secret` (admin) into every guest with `name=admin`, and the
  LXC path referenced a node-side secret file that doesn't exist, so it had
  never worked.
- Ceph gives you the right tool: `ceph fs authorize <fs> client.<name> <path> rw`
  mints a key scoped to the filesystem and subtree, and Tentacle's version takes
  `--key_type`. Proxmox still has no automation for this (true on 9.2), which
  is why it was admin-everywhere in the first place.

Decisions (operator): per-host identities named after the host; velorum keeps
`/ rw` (filestash browses the whole tree); delete the admin keyring and
`ceph.conf` from every client; both PVE storages get their own identities;
leave the aes-client `HEALTH_WARN` visible; neptune is the pmx workstation;
full live integration run.

## What changed in `pmx`

Commit: _see git log for "Stage E: per-guest CephX identities"_.

- **`mount_cephfs` mints `client.<guest_name>` on the node** (`tasks/cephx.yml`):
  `ceph auth get` decides existence; absent → `ceph fs authorize cephfs
  client.<name> <subpath> rw ... --key_type aes -o /dev/null`; present with
  different caps → `ceph auth caps` with the same strings `fs authorize`
  writes (filter `pmx_cephx_caps`); then `ceph auth get-key` → secret fact
  (`no_log`). VM path writes only `/etc/ceph/<name>.secret` (0600), deletes any
  `ceph.conf`/`cephfs.secret`/admin keyring, unmounts on a secret change
  (remount never re-authenticates), mounts with
  `name=<name>,secretfile=...,fs=cephfs,noatime,_netdev,recover_session=clean`,
  and asserts `findmnt` shows `name=<name>`. LXC path mounts per guest under
  `/mnt/pmx-passthrough/<name>/` with the secret on pmxcfs
  (`/etc/pve/priv/ceph/pmx-<name>.secret`, `x-systemd.requires=pve-cluster.service`)
  and writes `mp<N>:` lines idempotently.
- **`destroy.yml`** removes the entity (`ceph auth rm`, gated on `cephx_entity`
  from the state log so untracked guests never trigger it) and, for LXC, the
  host mounts, fstab lines, directory and secret.
- **State log** gains `cephx_entity`; **`verify`** checks the entity's MDS caps
  cover every subpath and each live mount is `name=<guest>`.
- **Preflight**: name uniqueness is now cluster-wide (`pvesh get
  /cluster/resources` via `pmx.cluster`; the old `qm list; pct list` check was
  node-local), reserved Ceph names are refused, and `--cephfs` refuses a
  pre-existing `client.<name>`.
- **Config**: `ceph_conf_path`/`ceph_secret_path` removed (a config still
  carrying them is refused with a hint); `cephx_key_type` added (default `aes`).
- Stage E extras: `rpm-reef` → `rpm-tentacle`; `discard=on` on seeded
  templates and attached RBD disks; `fstrim.timer` enabled by `common`.
- Tests: 115 unit tests green; `test_kitchen_sink.sh` now asserts identity,
  file hygiene, caps scope, reconfigure idempotence and destroy cleanup, and
  tears down via `pmx destroy`.

## Existing templates

_pending_ — `qm set 9000 --scsi0 bwrx:base-9000-disk-0,discard=on` and the same
for 9001.

## Migration of the hand-built clients

_pending_ — per-host table (entity, caps, mounts, verification).

## PVE storages and `client.admin`

_pending_ — bwrx → `client.bwrx`, cephfs → `client.pve-cephfs`, VM roll, admin
rotation.

## Integration run

_pending_.

## Health at the end

_pending_.

## Next: guest kernels → aes256k → drop `aes`

Ubuntu 24.04 offers the 26.04 kernel as HWE: `linux-generic-hwe-24.04` =
`7.0.0-31.31~24.04.1` (verified on tauron). No release upgrade needed; the
LTS→LTS upgrade isn't offered yet anyway.

0. Prove aes256k on a 7.0 client first, bounded: on a 26.04 host, mint a
   throwaway `client.aeskt --key_type aes256k` on `/template r`, mount, `ls`,
   unmount, `ceph auth rm`. If 7.0 refuses aes256k, stop here.
1. Per guest (pluto first — it's on 6.8.0-106 and overdue anyway):
   `apt install linux-generic-hwe-24.04 && reboot` (`qm reboot` for guests;
   ceres is physical). Verify `uname -r` is 7.0.x and the mounts came back.
2. Per guest: `ceph auth rotate client.<host> --key_type aes256k`, write the new
   secret, `umount` + `mount -a`. For pmx-managed guests set
   `cephx_key_type: aes256k` in the config and run `pmx reconfigure`.
3. When `ceph auth ls` shows no `aes` entity left: `ceph mon set
   auth_allowed_ciphers aes256k`. `AUTH_INSECURE_KEYS_ALLOWED`, `_CREATABLE`
   and `_CLIENT_KEY_TYPE` clear → `HEALTH_OK`. Flip the `cephx_key_type`
   default to `aes256k` in `pmx/config.py`, `group_vars/all.yml` and the role
   defaults.
