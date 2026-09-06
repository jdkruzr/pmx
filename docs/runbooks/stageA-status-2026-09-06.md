# Stage A status — PVE 9.2 + Ceph Tentacle upgrade

Living status for Stage A in
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).
Stage 0 closed 2026-09-06 01:30 — see
[`stage0-status-2026-09-05.md`](stage0-status-2026-09-05.md).

- **Started:** 2026-09-06 14:36
- **Approach:** canary one node end-to-end (kelvin), then roll the other three.
  Separate reboots for kernel and NIC pinning, so exactly one variable changes
  per reboot.

## Node progress

| Node | Remediations | dist-upgrade | Reboot 1 (kernel) | NIC pin | Reboot 2 | `pve8to9 --full` |
|---|---|---|---|---|---|---|
| kelvin | done | done | done | — | — | — |
| discovery | — | — | — | — | — | — |
| cerritos | — | — | — | — | — | — |
| excelsior | — | — | — | — | — | — |

## kelvin (canary)

**Evacuated first.** All 13 guests cluster-wide have zero local disks —
everything is on Ceph RBD — so every guest live-migrates with no storage copy.
kelvin's three moved with **74-93 ms downtime** each at 0.8-2.0 GiB/s:
106 (vulcan) and 111 (Pluto) → discovery, 115 (ntfy) → cerritos.

`ceph osd set noout` before starting, as `pve8to9` recommends.

**Remediations applied**, taking kelvin from 3 FAIL / 5 WARN to 2 FAIL / 1 WARN:

1. `apt-get remove systemd-boot` — the dry run confirmed it removes *only* that
   one package. `systemd-boot-efi` stays and is harmless. `efibootmgr` confirmed
   the real boot path is `Boot0002 proxmox → \EFI\proxmox\shimx64.efi` (GRUB via
   shim), so systemd-boot was never in the chain.
2. Added `non-free-firmware` to all three Debian suites in
   `/etc/apt/sources.list`, then installed `amd64-microcode`
   (3.20250311.1~deb12u1). Check now reads
   `PASS: Found matching CPU microcode package 'amd64-microcode' installed`.
3. `grub2/force_efi_extra_removable=true` via `debconf-set-selections` and
   `apt install --reinstall grub-efi-amd64`, refreshing
   `/boot/efi/EFI/BOOT/BOOTX64.EFI` (the stale `Boot0003 UEFI OS` fallback).

The two remaining FAILs are the ones the upgrade itself clears: `proxmox-ve`
< 8.4 (fixed by this stage) and Ceph Reef (Stage B).

**dist-upgrade:** rc=0 in **147 s**, 275 packages, run with
`--force-confold --force-confdef` so it could not stall on a config prompt —
conventional for a within-major point upgrade, but it does mean changed config
files kept the existing versions. Landed `pve-manager 8.4.21` (needs ≥ 8.4.1)
and `ceph 18.2.8` (needs ≥ 18.2.4-pve3). Both preconditions now met.

**Reboot 1:** kelvin had **over a year of uptime**, so a forced `fsck` on the
94 GB root was a live worry. It did not happen — SSH was back in **130 s**.
New `boot_id`, kernel **6.8.12-43-pve**, `pve-manager 8.4.21`, all nine services
active (`pve-cluster`, `corosync`, `pveproxy`, `pvedaemon`, `pvestatd`,
`ceph-mon@kelvin`, `ceph-osd@6`, `ceph-osd@7`, `ceph-mds@kelvin`), **zero failed
units**, `vmbr0` up on 192.168.9.14/24.

While kelvin was down the cluster behaved exactly as intended: quorum held at
3/4, 2 OSDs down, 28.98% of objects degraded but running 2-of-3 copies — above
`min_size=2`, so client I/O never stopped. Back to **97/97 PGs active+clean**
within seconds of the OSDs returning.

**Transient issue, resolved:** `clock skew detected on mon.kelvin` appeared
right after boot. chrony was already active and synchronized; the reported
0.111 s was accumulated offset being slewed, and it crossed back under Ceph's
50 ms MON threshold on its own. **Cleared after 75 s**, final offset 3.3 µs.
Expect this on every node reboot in Stages A and C — wait it out rather than
chasing it.

Ceph is now intentionally mixed, which is correct mid-roll:
kelvin's 4 daemons on 18.2.8, the other 12 on 18.2.2.

### Next on kelvin

NIC pinning, then reboot 2, then `pve8to9 --full`, then migrate 106/111/115
home and `ceph osd unset noout`.

**Do the pinning with the JetKVM physically attached.** `vmbr0` currently
bridges the bare `enp1s0f0`; `pve-network-interface-pinning generate` rewrites
`/etc/network/interfaces` to stable `nicN` names. It is the one step that edits
the network config of a machine reachable only over that network. Review the
generated file and confirm `vmbr0` references the pinned name before rebooting.
