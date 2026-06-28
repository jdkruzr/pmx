# Cluster runbooks

Operational playbooks for the Proxmox/Ceph cluster — diagnosing and recovering
from incidents on live nodes. These cover running-cluster operations, separate
from the `pmx` provisioning workflow documented elsewhere in `docs/`.

## Index

- [cephfs-client-wedged.md](cephfs-client-wedged.md) — a node's CephFS storage
  shows a gray `?` in the GUI and `/mnt/pve/cephfs` hangs on access; kernel
  client stuck on a stale MDS session after a failover.
