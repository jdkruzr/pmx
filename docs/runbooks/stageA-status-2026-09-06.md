# Stage A status — PVE 9.2 + Ceph Tentacle upgrade

Living status for Stage A in
[`pve9-ceph-tentacle-upgrade.md`](pve9-ceph-tentacle-upgrade.md).
Stage 0 closed 2026-09-06 01:30 — see
[`stage0-status-2026-09-05.md`](stage0-status-2026-09-05.md).

- **Started:** 2026-09-06 14:36
- **COMPLETED:** 2026-09-07 01:05 — all four nodes on pve-manager 8.4.21 /
  kernel 6.8.12-43-pve, all 18 Ceph daemons on 18.2.8, NICs pinned, `HEALTH_OK`.
  **Stage B is unblocked.**
- **Approach:** canary one node end-to-end (kelvin), then roll the other three.
  Separate reboots for kernel and NIC pinning, so exactly one variable changes
  per reboot.

## Node progress

| Node | Remediations | dist-upgrade | Reboot 1 (kernel) | NIC pin | Reboot 2 | `pve8to9 --full` |
|---|---|---|---|---|---|---|
| kelvin | done | done | done | **done** | **done** | **done** |
| discovery | done | done | done | **done** | **done** | **done** |
| cerritos | done | done | done | **done** | **done** | **done** |
| excelsior | done | done | done | **done** | **done** | **done** |

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

## cerritos — done 2026-09-06 16:32

dist-upgrade **rc=0 in 152 s**, reboot 1 **75 s**, reboot 2 **40 s**,
`pve8to9 --full` = **47 PASS / 1 FAIL** (one better than the earlier nodes — the
MDS version-mismatch warning cleared once 3 of 4 MDS were on 18.2.8). All three
guests home, `noout` cleared, HEALTH_OK. The two stopped templates (9000/9001)
stayed put through both reboots; stopped guests need no migration.

**Failed the mgr over deliberately first**, rather than letting the reboot force
it:

```bash
ceph mgr fail cerritos     # promoted discovery in well under a second
```

Worth doing on any node holding the active mgr — it turns an unplanned event
during shutdown into a controlled one you can verify before committing.

**Expect backfill after clearing `noout`.** PGs remapped while the node was
down, so unsetting the flag kicked off recovery: 9 remapped PGs, ~1% objects
misplaced, ~91 MiB/s. Health stays `HEALTH_OK` throughout (backfill is not a
warning), but **wait for `ceph pg stat` to return to all `active+clean` before
starting the next node.**

## excelsior — done 2026-09-07 01:05, and it hid the worst landmine of the upgrade

Ran the same recipe, but **excelsior came back from its first reboot still on
kernel 6.8.12-1 while the other three had moved to 6.8.12-43.**

### The kernel pin

`/etc/default/grub.d/proxmox-kernel-pin.cfg`, dated 2025-09-09:

```
GRUB_DEFAULT="gnulinux-advanced-<uuid>>gnulinux-6.8.12-1-pve-advanced-<uuid>"
```

Because `/etc/default/grub.d/*` is sourced *after* `/etc/default/grub`, this
pin overrode `GRUB_DEFAULT=0` and hard-bound the node to 6.8.12-1. `apt`
history shows why it existed — headers, that exact kernel, and
`thunderbolt-tools` all installed within six minutes on 2025-09-09.

**Why this mattered far more than a wrong kernel today:** in Stage C the Trixie
upgrade removes the 6.8 kernels and installs 7.0. A node pinned to a kernel
that no longer exists does not boot. On hardware with no IPMI, mid-dist-upgrade,
that is the single worst outcome this runbook is written to prevent.

**`pve8to9` does not catch it.** It reported
`PASS: running kernel '6.8.12-1-pve' is considered suitable for upgrade` — it
validates the *running* kernel, not the GRUB default. Three nodes upgrading
perfectly gave no hint the fourth was different. The only reason it surfaced was
noticing that `uname -r` said `-1` where the other nodes said `-43`.

**Check every node before Stage C:**

```bash
proxmox-boot-tool kernel list          # look for a "Pinned kernel" section
ls /etc/default/grub.d/                # look for proxmox-kernel-pin.cfg
grep -rhE '^GRUB_DEFAULT' /etc/default/grub /etc/default/grub.d/
```

Verified 2026-09-07: **no pins on any of the four nodes.** excelsior's was
removed with `proxmox-boot-tool kernel unpin` (which also clears
`/etc/kernel/next-boot-pin` and `/etc/kernel/proxmox-boot-pin` and re-runs
`update-grub`), then confirmed by rebooting onto 6.8.12-43.

Vestigial leftovers still installed on excelsior, harmless but removable:
`thunderbolt-tools 0.9.3-6` and `proxmox-headers-6.8.12-1-pve`. Confirmed with
the operator that the Thunderbolt work was an old experiment — no TB hardware
is present, no modules load, and dkms is not installed, so nothing was ever
compiled against the pinned kernel.

Otherwise unremarkable: dist-upgrade **rc=0 in 149 s**, reboots 45 s each,
`pve8to9 --full` = **50 PASS / 1 WARN / 1 FAIL**, guests home, `noout` cleared,
`HEALTH_OK`. excelsior runs neither mgr nor MDS, so no failover was needed.

## Final state

All four nodes identical: `pve-manager 8.4.21`, kernel `6.8.12-43-pve`, uplink
pinned to `nic1`, no kernel pins. Ceph: **18 daemons, all on 18.2.8** (4 mon,
3 mgr, 8 osd, 3 mds). 97 PGs active+clean, `HEALTH_OK`.

`pve8to9 --full` on the last node reports **50 PASS / 1 WARN / 1 FAIL** — the
version-mismatch warnings disappeared once the roll completed, and the only
remaining failure is `Hyper-converged Ceph 18 Reef is to old for upgrade!`,
which is precisely Stage B's cue.

## Techniques worth reusing in Stage C

- **Detect reboots by watching `/proc/sys/kernel/random/boot_id` change**, never
  by SSH reachability — sshd survives several seconds into shutdown and a naive
  poll will happily report pre-reboot state as success.
- **Fail the mgr over deliberately** (`ceph mgr fail <node>`) before rebooting
  whichever node holds it. ~2 s, and it beats letting shutdown force it.
- **Verify NIC pinning three ways before rebooting**: the `interfaces.new` diff,
  the `.link` file's `MACAddress`, and
  `udevadm test-builtin net_setup_link /sys/class/net/<iface>`. The tool has no
  `--dry-run`, but it writes to `interfaces.new` and leaves the live file intact
  until a successful boot.
- **Expect backfill after clearing `noout`** and wait for all-`active+clean`
  before starting the next node. On an idle cluster
  `ceph config set osd osd_max_backfills 4` roughly halves the wait; restore it
  to `1` afterwards.
- **Transient `mon` clock skew** after every node reboot clears itself in ~75 s.
  Do not chase it.
