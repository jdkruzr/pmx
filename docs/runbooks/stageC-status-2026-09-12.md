# Stage C status — PVE 8 → 9.2, Bookworm → Trixie, kernel 7.0

Companion to [`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).
Stage B completed 2026-09-09 (see [`stageB-status-2026-09-09.md`](stageB-status-2026-09-09.md)).

- **Pre-flight:** 2026-09-12 13:30–13:35 CDT — passed, see below
- **Operator location:** on-site (was remote for Stages 0–B). JetKVM in hand.

## Pre-flight (2026-09-12)

| Check | Result |
|---|---|
| Cluster | `HEALTH_OK`, 4/4 quorate, 97 PGs active+clean, 18/18 daemons on 19.2.5 |
| Nodes | all 8.4.21 / 6.8.12-43-pve, **no kernel pins**, ~5½ days uptime |
| `pve8to9 --full` × 4 | **50 PASS / 2 WARN / 0 FAIL** on every node (warns: `noout` unset, running guests — both expected) |
| Backups since staggering | **9 of 9 clean** over 3 nights (09-10, 09-11, 09-12). Concurrency was the cause. |
| PBS | every VM has 4 complete, verified copies; node configs **re-backed-up 2026-09-12 18:32 UTC** (~4 s each) |
| Trixie repos | all four Release files return 200: pve, ceph-squid, debian, debian-security |
| Target versions | `pve-manager` up to **9.2.18**, `proxmox-ve` 9.2.0, `proxmox-default-kernel` 2.1.0 → **proxmox-kernel-7.0 7.0.14-16** |
| Repo signing | trixie `Release.gpg` is signed by `A7BCD1420BFE778E` (Proxmox Trixie Release Key), **already present** in the nodes' `proxmox-archive-keyring` 3.3 — no keyring bootstrap needed |
| `ixgbe` tx-hang regression | fixed in 7.0.14-5; repo offers 7.0.14-16. Still push traffic over the 10G link per node before calling it done. |
| Per node | keyrings present, `tmux` **installed 2026-09-12** (was missing everywhere), ~79 GB free on `/`, 0 apt holds, `amd64-microcode` present, `non-free-firmware` in sources |
| Service placement | active **MGR: discovery**; active **MDS: cerritos** (moved there in Stage B) |

## Runbook corrections made before executing

1. **The deb822 template omitted `non-free-firmware`** and carried a note
   saying not to add it. That note predates Stage A, which added the component
   and installed `amd64-microcode` on every node at `pve8to9`'s request. Writing
   Trixie sources without it would strand the microcode package. Fixed.
2. **Config-prompt handling** was underspecified for a non-interactive run.
   Recorded the chosen approach: `--force-confold --force-confdef`, then diff
   every `*.dpkg-dist` under `/etc` afterwards and apply `lvm.conf` and
   `sshd_config` deliberately.
3. **Node order** rewritten for current placement: excelsior → kelvin →
   cerritos → discovery, with deliberate MDS/MGR failover before the last two.
4. **The between-node gate** now says `active+clean`, not "OSDs up" — the bug
   from the Stage B OSD roll-out.

## Things known going in that are not blockers

- ~~CephFS mounts still carry the old five-address `mon_host` string~~ —
  **wrong, struck 2026-09-12.** All four nodes rebooted in Stage A *after* the
  `mon_host` fix; excelsior's mount already showed four addresses before its
  Stage C reboot. Self-corrected days ago.
- `globus` (103, on discovery) has no PBS backup by prior decision. It
  live-migrates like everything else; this only matters if migration itself
  fails, which it has not once in 24 migrations so far.

## excelsior — canary, done 2026-09-12 14:02 CDT

| Step | Result |
|---|---|
| Evacuate | 104→cerritos 11 s, 105→discovery 15 s, 110→kelvin 9 s |
| `apt -s dist-upgrade` | 686 up / 175 new / **61 removed** — every removal a `t64` soname transition with its replacement in the install list; nothing from PVE/Ceph/corosync/qemu/boot/network removed; ZFS replaced (2.4.4) not dropped |
| dist-upgrade | **rc=0 in 248 s**, `dpkg --audit` clean |
| Reboot | back in **65 s** on `7.0.14-16-pve`, `pve-manager` 9.2.18, Ceph 19.2.6, `pve-qemu-kvm` **11.0.3** |
| NIC pinning under kernel 7.0 | **held** — `nic1`/`vmbr0` up on .13. First real test of the Stage A pinning; passed. |
| Gate (`active+clean`) | passed in 8 s; no clock skew this time |
| 10G traffic test | **9.40 Gbit/s sustained 22 s** (24 GiB, raw TCP via `nc`), 0 tx/rx errors, dmesg clean — ixgbe on 7.0.14-16 is fine |
| Guests home | 58 / 90 / 72 ms downtime; all three agents answer on the QEMU-11 host |

`noout` stays set for the rest of the stage.

### Two failed units mid-upgrade — expected, clears on reboot

After the dist-upgrade and **before** the reboot, `systemctl --failed` showed
`chrony.service` (`Could not send notification to $NOTIFY_SOCKET`) and
`user@0.service` (`Protocol driver not attached`, triggered by my own SSH login).
`/proc/1/maps` showed PID 1 was *already* systemd 257 — the upgrade had done a
`daemon-reexec` across a major version (252→257) on the still-running system.

I got the diagnosis wrong twice before getting it right, which is worth
recording so nobody repeats it on the other three nodes:

1. "It's the notify path to PID 1 being broken post-reexec" — **no**: five
   other `Type=notify` services (corosync, ssh, rpcbind, smartmontools,
   pve-lxc-syscalld) started after the reexec and were fine.
2. "It's chrony's seccomp filter vs new glibc on the old kernel" — **no**: the
   test I ran was invalid (my `systemd-run` probe lacked the unit's
   `RuntimeDirectory=chrony`, so it failed on privilege-drop regardless).

What actually settled it: stop debugging a service inside reexec limbo. The
system was otherwise coherent — `dpkg --audit` clean, `chronyd -v` linked,
config parsed, ssh/corosync/ceph/lvm all working — and a 5-minute clock gap is
harmless. **Reboot is both the fix and the test.** On the clean 7.0 boot both
units were active and `--failed` was empty.

**For kelvin/cerritos/discovery:** expect these two failures after the
dist-upgrade. Verify the system is coherent (audit clean, ssh/corosync/ceph
active, GRUB default on 7.0), then reboot. Don't chase chrony pre-reboot.

### `lvm.conf` — how to take the maintainer version without an unfiltered window

The wiki says "install maintainer version." Our PVE 8 file carried
`global_filter=["r|/dev/zd.*|","r|/dev/rbd.*|"]` under a
`# added by pve-manager to avoid scanning` marker; the pristine PVE 9 file has
no filter at all. On a Ceph cluster that filter is what stops the host's LVM
scanning every mapped RBD and activating guest VGs on the hypervisor.

`pve-manager.postinst` (9.2.18) manages this itself — new default adds `nbd`:
`["r|/dev/zd.*|","r|/dev/rbd.*|","r|/dev/nbd.*|"]` — **but skips when its
marker is already present**, which is why our file was left on the old value
even though the postinst ran. Naively copying the maintainer file leaves the
host unfiltered until something re-runs that logic.

Procedure used (no window): build `lvm.conf.new` = `lvm.conf.dpkg-dist` + the
exact block the postinst's `cat >>` branch writes, sanity-check it with
`LVM_SYSTEM_DIR=<tmp> lvmconfig`, then `mv` into place (atomic rename). Verify:

```bash
lvmconfig --typeconfig diff devices/global_filter   # 3-entry, with nbd
lvmconfig --typeconfig full devices/scan_lvs        # scan_lvs=0
lvmconfig --validate
pvs --noheadings -o vg_name                          # only pve + ceph-<osd> VGs
```

Old file kept as `/etc/lvm/lvm.conf.pve8-<date>`. `/etc/issue.dpkg-dist` is
simply deleted (wiki: keep ours — it's the PVE web-UI banner). No
`sshd_config.dpkg-dist` or `grub` prompt was generated on this node.

## Node progress

| Node | Evacuate | Sources | `-s` plan reviewed | dist-upgrade | Reboot → 7.0 | Verify + 10G traffic | Configs reviewed |
|---|---|---|---|---|---|---|---|
| excelsior | done | done | done | done | **done** | **done** | **done** |
| kelvin | — | — | — | — | — | — | — |
| cerritos | — | — | — | — | — | — | — |
| discovery | — | — | — | — | — | — | — |
