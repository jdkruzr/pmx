# Runbook: wedged kernel CephFS client on a node

Last verified: 2026-06-28

## Symptoms

- One node shows a gray `?` for the CephFS storage in the Proxmox GUI; the
  others are fine.
- Tab-completion or `ls` under `/mnt/pve/cephfs` on that node hangs and can't
  be killed with Ctrl-C.
- `ceph -s` reports `HEALTH_OK` the whole time — the cluster is healthy. The
  fault is entirely client-side on the one node.
- Load average on the node is inflated by processes stuck in `D`
  (uninterruptible sleep).

## Root cause

The node's kernel CephFS client gets stuck on a stale MDS session and can't
recover on its own. The sequence:

1. MDS rank 0 fails over to a different node (normal Ceph behavior).
2. The kernel client misses the new MDSMap and keeps trying to reach rank 0 at
   its old address.
3. Its cephx ticket to the monitors has lapsed, so re-auth fails with
   `mauth ... -13` (EACCES). Without a valid mon session it can never fetch a
   fresh MDSMap, so it loops forever.

The session state reads `mds.0 hung`, and every `stat()` against the mount
queues a request that will never get answered. We saw 2.2 million queued
`getattr` requests on inode `#1` (the CephFS root) in one occurrence.

A very long uptime makes this more likely — the incident on 2026-06-28 hit a
node with 684 days of uptime, long enough for a cephx ticket rotation to leave
the client unable to renew.

## Diagnosis

Run these from the affected node. None of them touch the hung mountpoint, so
they're safe — do **not** `ls /mnt/pve/cephfs` to check, or you'll hang the
shell too.

```bash
# Confirm processes are stuck in the ceph client, not elsewhere.
ps -eo pid,stat,wchan:32,cmd | awk '$2 ~ /D/'
#   -> D  ceph_mdsc_wait_request  ...   confirms the wedge

# Find the kernel client instance and read its session state.
ls /sys/kernel/debug/ceph/
D=/sys/kernel/debug/ceph/<fsid>.client<id>
cat $D/mds_sessions          # look for "mds.0 hung" (healthy is "open")
cat $D/status                # "blocklisted: false" rules out an eviction
wc -l < $D/mdsc              # depth of the stuck request backlog

# Confirm the cluster itself is healthy and the client never reconnected.
ceph -s                      # expect HEALTH_OK
ceph osd blocklist ls        # expect 0 entries (not a blocklist problem)
ceph tell mds.<active> session ls | grep -c <node-ip>   # 0 == no live session

# The kernel log shows the actual failure.
dmesg -T | grep -iE 'libceph|ceph' | tail -40
#   "wrong peer at address" + "mauth authentication failed: -13" == this runbook
```

Rule out the lookalikes before rebooting:

- **Clock skew** also causes cephx failures. Confirm it's *not* the cause:
  `ceph time-sync-status` should be clean and `timedatectl` should show the
  clock synced. On 2026-06-28 skew was 0 across all nodes, so the ticket had
  genuinely lapsed.
- **Blocklist eviction** looks similar but shows `blocklisted: true` and an
  entry in `ceph osd blocklist ls`. That's a different fix (remount after
  `ceph osd blocklist rm`).

## Remediation

A wedged kernel mount can't be repaired in place. It has to be torn down so it
re-auths from scratch and pulls the current MDSMap. Because of the `D`-state
tasks, a plain `umount` will itself hang, so the reliable fix is a reboot.

1. Migrate or shut down all guests on the node.

2. Set `noout` so Ceph doesn't rebalance the node's OSDs during the short
   reboot. Skip this only if the node runs no OSDs.

   ```bash
   ceph osd set noout
   ceph osd dump | grep flags    # confirm "noout" is listed
   ```

3. Confirm no guests are still running, then reboot. A graceful reboot lets the
   OSDs flush; the shutdown may stall briefly on the hung unmount, which is
   expected.

   ```bash
   qm list  | awk 'NR==1 || $3=="running"'
   pct list | awk 'NR==1 || $2=="running"'
   systemctl reboot
   ```

4. After it's back, verify recovery:

   ```bash
   mount | grep /mnt/pve/cephfs
   cat /sys/kernel/debug/ceph/*/mds_sessions      # expect "mds.0 open"
   timeout 10 ls /mnt/pve/cephfs >/dev/null && echo "no hang"
   ps -eo pid,stat,cmd | awk '$2 ~ /D/'           # expect none
   ceph tell mds.<active> session ls | grep -c <node-ip>   # now > 0
   ```

5. Clear `noout` and confirm health.

   ```bash
   ceph osd unset noout
   ceph osd tree         # node's OSDs up/in
   ceph -s               # HEALTH_OK
   ```

The GUI gray `?` clears within a poll cycle or two once `pvestatd` can stat the
storage again.

## Prevention

This is rare but tied to uptime: the longer a node runs, the more chances a
cephx ticket rotation coincides with an MDS failover and wedges the client.
Reboot (or `umount`/remount CephFS on) long-uptime nodes during routine
maintenance windows rather than letting them run for years. Rolling reboots one
node at a time — with `noout` set and waiting for `HEALTH_OK` between each —
keeps this from ever building up.
