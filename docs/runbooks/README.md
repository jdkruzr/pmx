# Cluster runbooks

Operational playbooks for the Proxmox/Ceph cluster — diagnosing and recovering
from incidents on live nodes. These cover running-cluster operations, separate
from the `pmx` provisioning workflow documented elsewhere in `docs/`.

## Index

- [cephfs-client-wedged.md](cephfs-client-wedged.md) — a node's CephFS storage
  shows a gray `?` in the GUI and `/mnt/pve/cephfs` hangs on access; kernel
  client stuck on a stale MDS session after a failover.
- [pve9-ceph-tentacle-upgrade.md](pve9-ceph-tentacle-upgrade.md) — planned
  three-stage upgrade of all four nodes from PVE 8.2 / Ceph Reef to PVE 9.2 /
  Ceph Tentacle 20.2 (Reef→Squid, then the OS dist-upgrade, then Squid→Tentacle).
- [stageE-status-2026-09-12.md](stageE-status-2026-09-12.md) — Stage E: per-guest
  CephX identities in `pmx`, migration of the hand-built CephFS clients off
  `client.admin`, PVE storages on their own keys, admin rotated to aes256k.
