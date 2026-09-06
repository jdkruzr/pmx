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
| kelvin | done | done | done | **done** | **done** | **done** |
| discovery | done | done | done | **done** | **done** | **done** |
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

### NIC pinning + reboot 2 — done

`pve-network-interface-pinning generate` is safer than it looks: it writes the
`.link` files to `/usr/local/lib/systemd/network/` and the new config to
`/etc/network/interfaces.**new**`, leaving the live file untouched until the
node reboots successfully. There is no `--dry-run`, but three independent
checks can be made before committing:

1. `diff /etc/network/interfaces /etc/network/interfaces.new` — confirm
   `bridge-ports` points at the new name and the address/gateway are unchanged.
2. Read the `.link` file for the uplink and confirm its `MACAddress=` is the
   NIC actually in the bridge.
3. `udevadm test-builtin net_setup_link /sys/class/net/<iface>` — reports the
   `ID_NET_NAME=` udev *would* assign, without changing anything.

On kelvin all three agreed: `enp1s0f0` (MAC `a0:36:9f:37:a8:58`) → `nic1`, with
`vmbr0 bridge-ports nic1`. Mapping was `enp6s0→nic0`, `enp1s0f0→nic1`,
`enp1s0f1→nic2`. The tool also rewrote `host.fw.new` and `sdn/controllers.cfg`,
both no-ops here (no host firewall rules, no SDN controllers).

Reboot 2 took **45 s** — much faster than reboot 1's 130 s, since no initramfs
regeneration was involved. Came back with `nic0/nic1/nic2`, `nic1` UP, `vmbr0`
UP on 192.168.9.14/24, `interfaces.new` applied and cleared, all nine services
active, zero failed units.

### `pve8to9 --full` (the real one, from 8.4.21)

**56 checks: 46 PASSED, 4 SKIP, 5 WARN, 1 FAIL** — from 3 FAIL at the start.

The single remaining failure is `Hyper-converged Ceph 18 Reef is to old for
upgrade!`, which is Stage B's job. All five warnings are artifacts of a
*partial* roll and are expected to clear as the other three nodes come through:
`HEALTH_WARN` (our own `noout`) plus "multiple running versions" for mon, MDS
and OSD — kelvin on 18.2.8 against 18.2.2 elsewhere.

### Wrap-up

106/111/115 live-migrated home (9 s each), `ceph osd unset noout`, and the
cluster returned to **HEALTH_OK** with 97/97 PGs active+clean and 8/8 OSDs
up/in.

## discovery — done 2026-09-06 16:03

Ran the kelvin recipe unchanged; no surprises. Guests out (galactica 100 → cerritos
10 s, globus 103 → excelsior 13 s), remediations, dist-upgrade **rc=0 in 137 s**,
reboot **130 s**, NIC pinning (`enp1s0f0` MAC `a0:36:9f:37:a9:08` → `nic1`, all
three checks agreed), second reboot, `pve8to9 --full` = **46 PASS / 1 FAIL**,
guests home, `noout` cleared, **HEALTH_OK**.

The mgr fix paid off immediately: discovery's mgr was a *standby* by then, so the
reboots were a non-event for the manager. Three mgrs throughout.

Two gotchas worth carrying to the remaining nodes:

- **Do not poll for "can I SSH in?" to detect a reboot.** sshd stays up for a
  few seconds into shutdown, so a naive poll connects to the *old* boot and
  reports success against pre-reboot state. Poll for
  `/proc/sys/kernel/random/boot_id` to **change** instead.
- **`ceph -s` can read fewer than 97 `active+clean` PGs** once `noout` is
  cleared and scrubbing resumes — PGs in `active+clean+scrubbing` are counted
  separately. `ceph pg stat` shows the real total. Not a problem; do not chase it.

## Roll plan for the remaining two

kelvin proved the procedure and discovery confirmed it. Remaining: **cerritos**
(currently holds the active mgr, so expect a ~2 s failover) and **excelsior**.
Per node, in this order:

1. `ceph osd set noout`
2. Live-migrate its guests off (all guests are on Ceph RBD; ~9 s and <100 ms
   downtime each)
3. Remove `systemd-boot`; add `non-free-firmware` + install `amd64-microcode`;
   set `grub2/force_efi_extra_removable` and reinstall `grub-efi-amd64`
4. `apt-get dist-upgrade` (~150 s)
5. Reboot; expect ~2 min back, and **expect a transient `mon` clock skew that
   clears itself in ~75 s**
6. `pve-network-interface-pinning generate`, verify with the three checks above,
   reboot (~45 s)
7. `pve8to9 --full`, migrate guests home, `ceph osd unset noout`, wait for
   `HEALTH_OK`

**mgr single-point-of-failure — fixed 2026-09-06.** discovery held the *only*
`mgr` in the cluster (`num_standby: 0`), so there was nothing to fail over to
and rebooting it would have meant a mgr outage. Rather than work around it,
added standbys:

```bash
pveceph mgr create      # on kelvin
pveceph mgr create      # on cerritos
```

Now three mgrs exist. Failover was then tested rather than assumed:

```bash
ceph mgr fail discovery
```

It promoted cerritos in **~2 seconds** with `HEALTH_OK` throughout, and
discovery rejoined as a standby. Current state: **cerritos active, discovery +
kelvin standby**. discovery can now be rebooted like any other node, and the
cluster has lost a real SPOF that predated this upgrade.

Stage B (Ceph Reef → Squid) should not begin until all four nodes are on
8.4.21, so the Ceph version mismatch warnings resolve first.
