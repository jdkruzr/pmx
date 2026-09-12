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

- Existing CephFS kernel mounts still carry the old five-address `mon_host`
  string (with the dead `.10`). The Stage C reboots remount with the corrected
  four-address string — a side benefit, not a task.
- `globus` (103, on discovery) has no PBS backup by prior decision. It
  live-migrates like everything else; this only matters if migration itself
  fails, which it has not once in 24 migrations so far.

## Node progress

| Node | Evacuate | Sources | `-s` plan reviewed | dist-upgrade | Reboot → 7.0 | Verify + 10G traffic | Configs reviewed |
|---|---|---|---|---|---|---|---|
| excelsior | — | — | — | — | — | — | — |
| kelvin | — | — | — | — | — | — | — |
| cerritos | — | — | — | — | — | — | — |
| discovery | — | — | — | — | — | — | — |
