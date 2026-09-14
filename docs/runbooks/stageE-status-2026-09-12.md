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

Pre-check (verified before anything was touched): `/etc/pve/priv/ceph/bwrx.keyring`
and `/etc/pve/priv/ceph/cephfs.secret` were byte-identical to the `client.admin`
key, so every running VM held the admin key in memory via librbd. Rotating
admin in place would have stalled their disks at the next mon
re-authentication (`auth_mon_ticket_ttl` 72 h, or any mon reconnect). Hence the
order: RBD storage first, roll the VMs, then CephFS storage, then admin.

**Step 1 — `client.bwrx` (19:28 CDT 2026-09-13).** Backups in
`/root/stageE-backup-2026-09-12/` on cerritos (`client.admin` export,
`bwrx.keyring.pre`, `cephfs.secret.pre`, `storage.cfg.pre`). Minted with
`ceph auth get-or-create client.bwrx mon 'profile rbd' osd 'profile rbd
pool=bwrx' mgr 'profile rbd pool=bwrx' --key_type aes256k` (key type 2),
written to `/etc/pve/priv/ceph/bwrx.keyring`, `pvesm set bwrx --username
bwrx`. `pvesm status` active on all four nodes, `rbd ls` as the new user
works, no pvestatd/pvedaemon errors.

**Step 2 — VM roll (out-and-back live migration, one VM at a time).** The
first three (ntfy, Pluto, vulcan) round-tripped at 45–91 ms downtime. Globus
then failed to start on the target: `"user":"bwrx"` … `error connecting: No
such file or directory`. **Finding:** PVE 9 starts VMs on new machine versions
with QEMU's blockdev syntax, which passes only `user` and
`conf=/etc/pve/ceph.conf` and leaves the keyring to ceph.conf's
`[client] keyring = /etc/pve/priv/$cluster.$name.keyring` — i.e.
`/etc/pve/priv/ceph.client.bwrx.keyring`, which did not exist. VMs still on
old machine versions (e.g. ntfy, `pc-i440fx-9.0`) use the legacy drive string
with an explicit `keyring=/etc/pve/priv/ceph/bwrx.keyring`, which is why they
worked; globus had been rebooted onto `pc-i440fx-11.0` today. Fix: the same
keyring written to `/etc/pve/priv/ceph.client.bwrx.keyring` as well (pmxcfs,
cluster-wide); `rbd -n client.bwrx -p bwrx ls` then resolves from every node
with no `--keyring`. **This is also why the admin rotation must update
`/etc/pve/priv/ceph.client.admin.keyring`: that is the file blockdev VMs
authenticate with.** Roll resumed from globus.

Roll result (19:37–19:50 CDT): all 11 VMs out and back, downtime 17–94 ms
per hop, every VM on its home node. Live QEMU command lines: ten VMs (machine
`pc-i440fx-9.0`) carry `id=bwrx:keyring=…`, globus (`pc-i440fx-11.0`,
blockdev) carries `"user":"bwrx"`. Mon sessions: 12 `client.bwrx`, 10
`client.admin` (the four nodes' CephFS mounts + transient CLI/pvestatd).
No VM holds the admin key any more.

**Step 3 — `client.pve-cephfs` (19:5x CDT).** Pre-check: a throwaway
`client.aeskt --key_type aes256k` (`/template r`) kernel-mounted fine on the
7.0.14-16-pve node kernel, so the storages go straight to aes256k. Minted
with `fs authorize cephfs client.pve-cephfs / rw --key_type aes256k`, key
written to `/etc/pve/priv/ceph/cephfs.secret`, `pvesm set cephfs --username
pve-cephfs`. Then per node (cerritos, discovery, excelsior, kelvin): `fuser`
clear, `umount /mnt/pve/cephfs`, pvestatd remounted it within 5–10 s as
`name=pve-cephfs`, `ls` responsive. MDS session list: four `client.pve-cephfs`
sessions, **zero `client.admin` anywhere**.

**Step 4 — `client.admin` → aes256k.** Backup of the keyring file taken;
`ceph auth rotate client.admin --key_type aes256k` printed the new key (the
`mon.` keyring on cerritos was the prepared fallback for reading it back);
new key + the existing caps lines written to
`/etc/pve/priv/ceph.client.admin.keyring` (pmxcfs, so all nodes at once).
Verified: key type 2, file == auth DB, `ceph -s` from every node with its own
copy, zero pvestatd/pvedaemon auth errors, `bwrx` and `cephfs` active on all
four nodes. `client.admin` is now held by nothing but the CLI.

Final client entities and key types: `admin` **2**, `bwrx` 2, `pve-cephfs` 2,
`crash` 2, `bootstrap-*` 2; `ceres`, `neptune`, `pluto`, `tauron`, `velorum`
1 (aes, until their kernels move — see Next).

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
- **Run 9**: `test_create_lxc.sh` built and configured both containers; the
  Rocky one failed the harness's `which tmux && …` check with rc 127 because
  the Rocky container image has no `which`. Harness fix: `command -v`
  everywhere (the kitchen-sink LXC check had the same landmine).
- **Run 10**: `test_create_lxc.sh` **passed** (both OS families).
  `test_ad_join.sh` built and joined the Ubuntu VM (AD Administrator
  resolves with full group membership) and then failed
  `getent group domain_admins`: the group came back as `domain admins`.
  Cause: `override_space = _` sat in the `[domain/…]` section of the sssd
  template, where sssd silently ignores it (it is a `[sssd]`-section option,
  SPECIAL SECTIONS in sssd.conf(5)). So the underscore convention that the
  design, the role defaults, the sudoers drop-in's comment and the harness
  all assume had never been in effect on any pmx guest. Proven on the joined
  guest: moved to `[sssd]` → `getent group domain_admins` resolves, `id`
  shows underscore names, `sudo -l -U jtd` matches. Fixed in the template;
  sudoers now carries both `%domain_admins` and `%domain\ admins`.
- **Run 11**: `getent group domain_admins` now resolves (underscore names
  throughout `id`); the harness then failed its sudoers check, which it ran
  as the unprivileged `ansible` user against root-only `/etc/sudoers.d`.
  Harness fix: sudo prefix on VMs (as `pmx verify` already does).
- **Run 12**: Ubuntu VM and Ubuntu LXC joined and passed every check. The
  Rocky VM's `realm join` failed (output hidden by `no_log`). By hand with
  `-v`: first `realm: Unknown option --stdin-password` — Rocky's realmd
  0.17.1-2.el9 lacks the flag Ubuntu's build has (the Ubuntu role never used
  it; `--unattended` reads stdin anyway). With that removed, the real error:
  `KDC has no support for encryption type`. EL9's DEFAULT crypto policy
  permits only AES Kerberos enctypes; the Zentyal Samba 4.19 KDC offers the
  join account (`jtd`, no `msDS-SupportedEncryptionTypes`) RC4 only. Plain
  `AD-SUPPORT` did not help (it no longer enables RC4 since RHEL 9.4);
  `DEFAULT:AD-SUPPORT-LEGACY` adds `arcfour-hmac-md5` and the join succeeded.
  Fixed in `ad_join_rocky`. **Operator follow-up (DC side, better fix):** give
  the join account and computer objects AES keys — e.g. set
  `msDS-SupportedEncryptionTypes = 24` (AES128+AES256) or `28` (RC4+AES) on
  `jtd` via `samba-tool`, or `kdc default domain supported enctypes = 28` on
  the DC — after which the LEGACY subpolicy can be dropped again.
- **Run 13**: the Rocky VM joined the domain (the two fixes hold); the run
  then failed on the shared `reload ssh` handler, which named the unit `ssh`
  — that is Ubuntu's name; on EL it is `sshd`. Handler made OS-aware.
- **Run 14**: Ubuntu VM, Ubuntu LXC and **Rocky VM** all joined and passed.
  The Rocky LXC failed at the new crypto-policy step: the container image
  has no `update-crypto-policies` (`crypto-policies-scripts` not installed).
  Added to the Rocky join package list.
- **Run 15**: `test_ad_join.sh` **passed** — all four combinations joined
  and verified. `test_kitchen_sink.sh`: the **VM half passed every check**,
  which is the per-guest CephX path end to end (entity minted with
  `path=/supernote` caps, mount `name=<guest>`, only `<guest>.secret` 0600 on
  the guest, `pmx verify` green, `pmx reconfigure` with no `mount_cephfs`
  changes, `pmx destroy` removing the entity). The LXC half failed before
  creating anything: `ansible.utils.ipmath` (gateway inference when
  `--static-gw` is omitted) needs `netaddr` on the controller and it was never
  a declared dependency. Added to `pyproject.toml` + `uv.lock`.
- **Run 16**: VM half passed again; the LXC half minted its entity and then
  failed writing the secret to `/etc/pve/priv/ceph/`: pmxcfs refuses the
  `copy` module's atomic temp-file rename (`Operation not permitted` on
  `.ansible_tmp*`). A direct write works; the task is now a content-aware
  shell write. (The build failed before `post_create_hook`, so the entity was
  untracked and had to be removed by hand — `pmx destroy` only removes
  entities it recorded.)
- **Run 17**: VM half passed; **the LXC CephFS path now works on the node**:
  `client.<lxc>` minted, secret on pmxcfs, host mount
  `/mnt/pmx-passthrough/<lxc>/supernote` authenticated as `name=<lxc>`, fstab
  line with `x-systemd.requires=pve-cluster.service`, `mp0:` line in the
  container config, `/mnt/sn` visible inside the container. It then failed
  in `extra_packages`: `htop` is EPEL-only on Rocky and pmx does not enable
  EPEL. Harness asks for `jq,nano` (base repos) on the Rocky container
  instead. Untracked leftovers (build died before `post_create_hook`) were
  cleaned by hand, mirroring `destroy.yml`.
- **Run 18**: `test_kitchen_sink.sh` **passed both halves.** All six
  harnesses are green: lifecycle, state log, create VM, create LXC, AD join
  (4 combinations), kitchen sink (VM + LXC with CephFS).

Post-run sweep (04:15 CDT): no `pmxtest` guests, entities, passthrough
mounts, fstab lines or pmxcfs secrets on the cluster; MDS admin sessions
still exactly the four nodes. Neptune's state log restored as the original
7 records + the 51 test records, then every record for a test guest that no
longer exists tombstoned (harnesses that tear down with raw `qm`/`pct`
never tombstone); only `ntfy` is live. Those raw teardowns had also left
computer objects on the DC (`PMXTEST-UBUNTU-$`, `PMXTEST-ROCKY-V$`,
`PMXTEST-ROCKY-L$` — NetBIOS names truncate to 15 chars and collide across
runs) and A/PTR records; all removed with `dc_dereg.sh`, and
`test_ad_join.sh` now tears down via `pmx destroy` so this stops recurring.

### Defects the run found and fixed (none in the CephX code itself)

| Where | Defect | Fix |
|---|---|---|
| `create_vm` + seed roles | No CPU type → `kvm64` (x86-64-v1) under QEMU 11; EL9 panics at init (`Fatal glibc error: CPU does not support x86-64-v2`). **The one true upgrade regression.** | `--cpu x86-64-v2-AES` on clones and templates; 9000/9001 pinned by hand |
| `create_vm` | `network-get-interfaces` raced the DHCP lease once Rocky booted fast | retry until an IPv4 appears |
| `create_lxc` | Rocky LXC template has no `openssh-server`; configure play never reached a Rocky container | `pct exec` installs/enables sshd, `wait_for` 22 |
| `common/rocky` | No cloud-init wait; PVE's `package_upgrade: true` ran dnf concurrently with the role's | wait, and plain `dnf -y upgrade --refresh` |
| `ad_join_rocky` | `--stdin-password` unknown to EL9 realmd; EL9 DEFAULT policy vs RC4-only KDC | drop the flag; `DEFAULT:AD-SUPPORT-LEGACY`; `crypto-policies-scripts` for LXC |
| `ad_join_common` | `override_space` in the wrong sssd section since April; `reload ssh` handler named Ubuntu's unit | moved to `[sssd]`; sudoers has both group spellings; handler OS-aware |
| `post_create_hook` | create records lacked `destroyed_at` | emitted as `""` |
| `mount_cephfs/lxc` | pmxcfs rejects the copy module's atomic rename | direct content-aware write |
| deps | `netaddr` (ansible.utils ipmath) never declared | `pyproject.toml` |
| harnesses | pvestatd lag on the orphan case; padded uid_map grep; `which` on Rocky; sudoers check without sudo; `.80` is bifrost; EPEL-only `htop` on Rocky; raw teardown | all fixed |

## Health at the end (20:05 CDT 2026-09-13)

```
HEALTH_WARN 5 auth client entities with insecure key types;
            Monitors are configured to allow auth using insecure key types;
            Monitors are configured to allow creation of insecure key types;
            6 OSD(s) experiencing slow operations in BlueStore
```

- `AUTH_INSECURE_CLIENT_KEY_TYPE` — exactly the five guest keys (`ceres`,
  `neptune`, `pluto`, `tauron`, `velorum`), all on `aes` because their Ubuntu
  24.04 kernels (6.8) cannot use aes256k client keys. Expected; left visible
  by operator decision. Clears with the kernel work in "Next".
- `AUTH_INSECURE_KEYS_ALLOWED` / `_CREATABLE` — `auth_allowed_ciphers` must
  keep `aes` while those five exist. Same exit condition.
- `BLUESTORE_SLOW_OP_ALERT` (new in Tentacle) — six OSDs saw at least one slow
  BlueStore op in the last 24 h (`bluestore_slow_ops_warn_lifetime` 86400,
  threshold 1). OSD latencies are 0–38 ms and client I/O idle at the time of
  writing; this is the footprint of 18 integration-harness runs, 22 live
  migrations and the 02:00–03:00 PBS jobs, and ages out on its own.
- The D+ note claiming `AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE` self-clears
  within one `auth_service_ticket_ttl` was wrong: it cleared between 17:19
  and 18:49 CDT, roughly two to three ticket lifetimes after the cipher change.

Everything else: 97 PGs `active+clean`, all 11 VMs running on their home
nodes, all five CephFS clients responsive, `pvesm status` active for `bwrx`
and `cephfs` on all four nodes.

Operator items left open after this session:

- Delete `~/.config/pmx/ad_password` on neptune (created for the harness run).
- Globus: remove the stale admin artefacts in `/etc/ceph` (dead keys now) and
  install `qemu-guest-agent`; sysop's sudo needs a password there.
- DC side: give AD accounts AES Kerberos keys so Rocky guests no longer need
  the `AD-SUPPORT-LEGACY` crypto subpolicy (see Run 12 above).

## Guest kernels → aes256k (executed 2026-09-13 evening CDT)

Per guest: `apt-get install linux-generic-hwe-24.04` (7.0.0-31), reboot
(`qm reboot`, boot_id-gated; ceres physical), verify kernel + mounts +
services, then `ceph auth rotate client.<H> --key_type aes256k`, new secret
over stdin, umount / `mount -a` with services paused, verify.

**Finding that changed the plan:** the throwaway aes256k key test on pluto's
fresh 7.0.0-31-generic kernel *failed* (`libceph: auth protocol 'cephx' init
failed: -22`) although the same test had passed on the nodes' 7.0.14-16-pve.
Bypassing the mount helper (`mount -i … -o secret=`) succeeded, so the kernel
is fine and the culprit is Ubuntu's `mount.ceph` from ceph-common 19.2.3
(Squid), which mangles the aes256k blob. Ceph publishes Tentacle for noble
(`debian-tentacle`, ceph-common 20.2.4-1noble); with that installed the
normal `secretfile=` mount works. So every guest also got Ceph's Tentacle
apt repo + ceph-common 20.2.4, and `mount_cephfs` now does the same for
Ubuntu guests.

| Host | Kernel | ceph-common | `client.<H>` | Result |
|---|---|---|---|---|
| pluto | 7.0.0-31 | 20.2.4 | aes256k (2) | mount back at boot, deluge up; rotation + remount OK |
| tauron | 7.0.0-31 | 20.2.4 | aes256k (2) | Nextcloud `status.php` OK before and after |
| velorum | 7.0.0-31 | 20.2.4 | aes256k (2) | filestash containers up; root mount OK |
| neptune | 7.0.0-31 | 20.2.4 | aes256k (2) | ultrabridge restarted around the remount, sees its binds |
| ceres | _in progress_ | | | NVIDIA 595.84 DKMS confirmed built for 7.0.0-31 before rebooting |

## Next: drop `aes`

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
