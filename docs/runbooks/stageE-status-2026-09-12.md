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

Done 2026-09-12 17:2x CDT: `qm set 9000 --scsi0 bwrx:base-9000-disk-0,discard=on`
and `qm set 9001 --scsi0 bwrx:base-9001-disk-0,discard=on`. Clones inherit it.

## Migration of the hand-built clients

Recipe per host (`H`), node side on cerritos, guest side as root:

1. `ceph fs authorize cephfs client.$H <sub> rw [<sub> rw ...] --key_type aes -o /dev/null`;
   `ceph auth get client.$H` to eyeball the caps; `ceph auth get-key client.$H`
   piped over stdin to the guest (never on a command line).
2. Guest: `umask 077; cat > /etc/ceph/$H.secret` (root:root 0600);
   `cp -n /etc/fstab /etc/fstab.pre-stageE`; on the ceph lines only:
   `name=admin,secretfile=/etc/ceph/cephfs.secret` →
   `name=$H,secretfile=/etc/ceph/$H.secret,fs=cephfs` and
   `_netdev` → `_netdev,recover_session=clean`.
3. Guest: stop whatever might open files, `umount` the mounts, **then** delete
   `ceph.client.admin.keyring`, `cephfs.secret`, `ceph.conf`, then `mount -a`,
   restart services.
4. Verify: `findmnt -t ceph -o TARGET,SOURCE,OPTIONS` shows `name=$H`,
   `mds_namespace=cephfs`, `recover_session=clean`; root `ls` + touch/rm on each
   mount; `/etc/ceph` holds only `$H.secret` (+ `rbdmap`); MDS `session ls`
   (`auth_name.id`) shows the host under `client.$H` and no longer under admin.

Findings that apply to every host:

- **Mounting without `ceph.conf` works** but `mount.ceph` (19.2.3) grumbles:
  "can't open ceph.conf", "unable to get monitor info from DNS SRV", "unable to
  find a keyring on /etc/ceph/ceph.client.<H>.keyring…". All noise: mons come
  from the fstab source, the secret from `secretfile=`, and dmesg shows the mon
  session and real fsid. The only visible side effect is `fsid=0000…` in the
  mount options, cosmetic.
- `fs=cephfs` is shown back by the kernel as `mds_namespace=cephfs`.
- Directories owned by service users (`ncdata`/`nextclouddata` are 770
  `www-data`) give an unprivileged `ls` "Permission denied": POSIX, not CephX.
  Verify as root.

| Host | Entity | Caps (mds) | Mounts | Result |
|---|---|---|---|---|
| tauron (.40) | `client.tauron` | `path=/nextclouddata`, `path=/ncdata` | `/mnt/nextclouddata`, `/mnt/ncdata` | 17:38 CDT. php-fpm + apache2 stopped ~5 s around the remount. Both mounts `name=tauron`; root ls + write OK; Nextcloud `status.php` installed, not in maintenance (34.0.0). MDS: 2 sessions as `client.tauron`, 0 as admin from tauron. |
| ceres (.199, physical) | `client.ceres` | `path=/nextclouddata/jtd/files/onyx`, `path=/nextclouddata/jtd/files/Saber` | `/mnt/onyx`, `/mnt/saber` | 18:03 CDT. Nothing held the mounts; llama-server kept running. Both `name=ceres`; root ls + write OK; MDS 2 sessions as `client.ceres`. Admin sessions cluster-wide: 13 → 9. |
| pluto (.72) | `client.pluto` | `path=/deluge` | `/mnt/deluge` | 18:16 CDT. Guest side via `qm guest exec 111` (sysop sudo needs a password there); secret staged over sysop's stdin, root `install`ed it. `deluged` + `deluge-web` stopped ~5 s. The operator's own shell was parked in `/mnt/deluge/Completed` and had to move first (umount would have hit EBUSY) — the script checks `fuser -m` and refuses before touching anything. `name=pluto`, ls + write OK. Admin sessions: 9 → 8. |
| velorum (.70) | `client.velorum` | `allow rw fsname=cephfs` (root scope, operator decision: filestash browses the whole tree) | `/mnt/cephfs` | 18:17 CDT. Via `qm guest exec 110`. No holders; filestash containers use a docker volume, not the mount, and stayed up. `name=velorum`, ls + write OK. Admin sessions: 8 → 7. |
| neptune (.52, also the pmx workstation) | `client.neptune` | `path=/supernote`, `path=/remarkable`, `path=/nextclouddata/jtd/files/onyx` | `/mnt/supernote`, `/mnt/remarkable`, `/mnt/onyx` | 18:49 CDT. `docker stop ultrabridge` first (it binds supernote + remarkable), holders re-checked, three umounts, `mount -a`, `docker start`; `docker exec ls` inside the container shows 38 / 6 entries on the re-attached binds. All three `name=neptune`, ls + write OK. Admin sessions: 7 → 4. |

After neptune, `session ls` shows exactly four `client.admin` sessions — the
nodes' own `/mnt/pve/cephfs` storage mounts (root `/`) — and every other
session under its host's own entity.

**Globus** (.50): no CephFS mount (unit static, never active), but it still has
the three world-readable admin artefacts in `/etc/ceph`. sysop's sudo needs a
password there and the guest agent isn't installed, so this is an operator
item: `sudo rm /etc/ceph/ceph.client.admin.keyring /etc/ceph/cephfs.secret
/etc/ceph/ceph.conf` (and `sudo apt install qemu-guest-agent` while you're in
there). After the admin rotation below those files are dead keys anyway.

## PVE storages and `client.admin`

_pending_ — bwrx → `client.bwrx`, cephfs → `client.pve-cephfs`, VM roll, admin
rotation.

## Integration run

From neptune (`/home/sysop/proxmox-manage`, `PMX_LIVE=1`, AD password from a
0600 file the operator created for the run), all six harnesses in sequence,
each to `/tmp/stageE-tests/<harness>.log`. Neptune's real `state/guests.jsonl`
(ntfy's live record, cumulus' history) was backed up first because
`test_state_log.sh` deletes it; restored with the test records appended after.

- **Run 1, `test_lifecycle.sh`:** create → verify → reconfigure ×2 → destroy
  and the `--no-domain` LXC all passed (the new CephX teardown tasks in
  `destroy.yml` correctly reported *skipped* for guests without mounts). The
  final orphan case failed: the harness `pct create`s a container and
  immediately calls `pmx destroy`, and the cluster-wide lookup
  (`pvesh get /cluster/resources`, refreshed by pvestatd every ~10 s) did not
  list it yet. The old node-local `pct list` never had that lag. Fixed in the
  harness (`ce4bc87`): poll for the name before destroying. The leftover
  orphan was destroyed by hand with `pmx destroy` — which is the AC12.3 path
  and behaved: "not in state log" warning, destroy, CephX steps skipped.
- **Run 2:** `test_lifecycle.sh` **passed** end to end (6 min 42 s).
  `test_state_log.sh` then failed on its first assertion: the fresh create
  record lacked `destroyed_at`. Pre-existing: the Ansible writer in
  `post_create_hook` never emitted that field, only the Python tombstone
  writer did, and the harness asserts a live record carries it as `""`.
  Fixed (`95b354e`): both writers now produce the same record shape. The
  leftover container was destroyed with `pmx destroy` (tombstoned cleanly).
- **Run 3** (`test_state_log` onward): the Ubuntu container passed; the Rocky
  container was `UNREACHABLE` at Gathering Facts, "connection refused" on 22.
  Inside it: `Unit sshd.service could not be found` — the only Rocky 9 LXC
  template on offer (`rockylinux-9-default_20240912`) ships **without
  openssh-server**, and `create_lxc` never installed one, so a Rocky container
  has never been reachable by the configure play. Not an upgrade regression,
  just never exercised to completion. Fixed (`4fb19f8`): after the IP is
  known, `pct exec` installs/enables sshd (Rocky: `dnf openssh-server` +
  `sshd`; Ubuntu: ensure `ssh`) and the role `wait_for`s port 22 before
  `add_host`. Leftovers destroyed with `pmx destroy` (one tracked, one not).
- **Run 4** (`test_state_log` onward): `test_state_log.sh` **passed** (the
  Rocky container came up with sshd and was configured; both records carry
  every field). `test_create_vm.sh`: the Ubuntu VM passed; the Rocky VM never
  raised its guest agent and never even appeared in ARP. Its serial log
  (captured across a reset) ends in
  `Fatal glibc error: CPU does not support x86-64-v2` →
  `Kernel panic - not syncing: Attempted to kill init!`. **This one is a real
  upgrade regression:** no template sets a `cpu:` type, so under QEMU 11 the
  VM runs as the deprecated `kvm64` ("Common KVM processor", x86-64-v1);
  EL9 userland requires v2. Ubuntu tolerates v1, Rocky does not. Proven on
  the failing VM: `qm set 107 --cpu x86-64-v2-AES` + stop/start → agent
  answered in 10 s (note `qm reset` is not enough; the CPU model only changes
  on a fresh QEMU process). Fixed (`create_vm` sets `--cpu x86-64-v2-AES` on
  every clone; both seed roles bake it into templates); templates 9000/9001
  pinned by hand. All four nodes are Zen 4, so v2-AES migrates freely.
- **Run 5** (`test_create_vm` onward): Ubuntu VM passed; the Rocky VM now
  booted (CPU fix works) but failed one step later: "did not acquire an IPv4
  address via guest agent". The agent answered `ping` before DHCP finished
  and the single `network-get-interfaces` query saw no address; a minute
  later the VM had `.125`. Fixed: the query retries until an IPv4 appears.
- **Run 6** (`test_create_vm` onward): the Rocky VM booted, leased (`.126`)
  and was reachable; the configure play then failed at `common: dnf upgrade`
  with the dnf module's "An rpm exception occurred: package not installed".
  Re-running the same module call ad hoc against that guest reported
  "Nothing to do" and the guest was at 9.8, so the transaction had applied
  and I first blamed a package the upgrade obsoleted. Changed the task to a
  plain `dnf -y upgrade --refresh`.
- **Run 7**: plain dnf failed differently after 2 min 50 s:
  `No such file or directory: /var/cache/dnf/.../packages/bluez-*.rpm` — a
  downloaded package vanished mid-transaction. **Actual root cause:** PVE's
  cloud-init user-data sets `package_upgrade: true`, so a fresh VM runs its
  own `dnf upgrade` at first boot, concurrently with the role's. Ubuntu's task
  list has always begun with `cloud-init status --wait`; Rocky's never did.
  Fixed: Rocky now waits for cloud-init too (plain dnf kept; it is the more
  robust of the two either way).
- **Run 8**: `test_create_vm.sh` **passed** (Ubuntu and Rocky VMs built,
  configured, verified). `test_create_lxc.sh` failed on its own uid-map
  assertion: `/proc/self/uid_map` is `%10u`-padded and the harness grepped
  for single spaces, so that check could never have matched. Harness fixed
  (`62d75c3`). Leftover guests destroyed via `pmx destroy`.
- **Run 9** (`test_create_lxc` → `test_ad_join` → `test_kitchen_sink`):
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
