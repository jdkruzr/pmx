#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
source "${REPO_ROOT}/tests/integration/_guard.sh"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD first.}"

NODE=root@192.168.9.12

# Fail if any mount_cephfs task reported "changed" in an ansible log — the role
# must be a no-op on a second run against an already-configured guest (AC8.3).
assert_mount_cephfs_idempotent() {
  local log="$1"
  if awk '/^TASK \[/ {task=$0} /^changed: / && task ~ /mount_cephfs :/ {print task; found=1} END {exit !found}' "$log"; then
    echo "mount_cephfs reported changes on reconfigure (not idempotent)" >&2
    return 1
  fi
}

NAME="pmxtest-kitchen-$$"

echo "=== Building kitchen-sink VM: ${NAME} ==="
uv run pmx new --name "${NAME}" --kind vm --os ubuntu \
  --cores 2 --memory 2048 --disk 32 \
  --cephfs supernote:/mnt/sn \
  --rbd-disk 10 \
  --extra-packages htop,jq \
  --static-ip 192.168.9.80/24 --static-gw 192.168.9.1

vmid=$(ssh ${NODE} "qm list | awk -v n=${NAME} '\$2==n{print \$1}'")
echo "VMID: ${vmid}"

# Verify extra disk attached, with discard (AC9.1)
ssh ${NODE} "qm config ${vmid} | grep -E '^scsi1:\s+bwrx:.+,discard=on.*,size=10G'"

# Verify static IP (AC11.1)
ssh -o StrictHostKeyChecking=accept-new ansible@192.168.9.80 \
  "ip -4 addr show | grep -q 'inet 192.168.9.80/24'"

# Verify cephfs mount (AC8.1) — and that it authenticates as the guest's OWN identity
ssh ansible@192.168.9.80 "findmnt /mnt/sn | grep -q ceph"
ssh ansible@192.168.9.80 "findmnt -rn -t ceph -o OPTIONS /mnt/sn | tr ',' '\n' | grep -qx name=${NAME}"

# Only the guest's own secret lives on the guest, root-only; no admin artefacts
ssh ansible@192.168.9.80 "sudo stat -c %a /etc/ceph/${NAME}.secret | grep -qx 600"
ssh ansible@192.168.9.80 "! test -e /etc/ceph/ceph.client.admin.keyring && ! test -e /etc/ceph/ceph.conf && ! test -e /etc/ceph/cephfs.secret"

# The entity on the cluster is scoped to exactly the requested subpath
ssh ${NODE} "ceph auth get client.${NAME} -f json | grep -q 'path=/supernote'"

# Verify extra packages (AC10.1)
ssh ansible@192.168.9.80 "which htop && which jq"

# fstrim.timer is on (disks carry discard=on)
ssh ansible@192.168.9.80 "systemctl is-enabled fstrim.timer"

# verify sees the cephx caps + mount identity
uv run pmx verify "${NAME}"

# reconfigure is idempotent for the CephFS role (AC8.3)
uv run pmx reconfigure "${NAME}" 2>&1 | tee /tmp/ks-reconf-vm.log
assert_mount_cephfs_idempotent /tmp/ks-reconf-vm.log
ssh ansible@192.168.9.80 "findmnt -rn -t ceph -o OPTIONS /mnt/sn | tr ',' '\n' | grep -qx name=${NAME}"

# Cleanup via pmx so the CephX identity goes with the guest
uv run pmx destroy "${NAME}" --yes
ssh ${NODE} "! ceph auth get client.${NAME} >/dev/null 2>&1"

echo "=== Kitchen-sink VM passed all checks ==="

# Now the LXC variant (no --rbd-disk; LXC rejection was covered in Task 1 unit test).
LXC_NAME="pmxtest-kitchen-lxc-$$"
HOST_MNT="/mnt/pmx-passthrough/${LXC_NAME}/supernote"

echo "=== Building kitchen-sink LXC: ${LXC_NAME} (NOTE: --static-gw deliberately omitted — exercises the .1-of-subnet inference path) ==="
uv run pmx new --name "${LXC_NAME}" --kind lxc --os rocky \
  --cores 1 --memory 1024 --disk 8 \
  --cephfs supernote:/mnt/sn \
  --extra-packages htop,jq \
  --static-ip 192.168.9.81/24

lxc_vmid=$(ssh ${NODE} "pct list | awk -v n=${LXC_NAME} '\$NF==n{print \$1}'")
echo "LXC VMID: ${lxc_vmid}"

# Verify LXC mp line exists and points at the per-guest host mount (AC8.2, AC2.3)
ssh ${NODE} "grep -E '^mp[0-9]+: ${HOST_MNT},mp=/mnt/sn' /etc/pve/lxc/${lxc_vmid}.conf"

# Host-side mount authenticates as the container's own identity; secret on pmxcfs
ssh ${NODE} "findmnt -rn -t ceph -o OPTIONS ${HOST_MNT} | tr ',' '\n' | grep -qx name=${LXC_NAME}"
ssh ${NODE} "test -f /etc/pve/priv/ceph/pmx-${LXC_NAME}.secret"

# Verify mount is visible inside container
ssh ${NODE} "pct exec ${lxc_vmid} -- findmnt /mnt/sn | grep -q /mnt/sn"

# Verify static IP on LXC (AC11.2)
ssh -o StrictHostKeyChecking=accept-new root@192.168.9.81 \
  "ip -4 addr show | grep -q 'inet 192.168.9.81/24'"

# Verify inferred gateway picked up the .1-of-subnet default (AC11.2, Critical 2 regression guard)
ssh root@192.168.9.81 "ip -4 route show default | grep -q '192.168.9.1'"

# Verify extra packages (AC10.1 on Rocky via dnf)
ssh root@192.168.9.81 "which htop && which jq"

uv run pmx verify "${LXC_NAME}"

# reconfigure must not duplicate the mp line nor re-mint anything (AC8.3)
uv run pmx reconfigure "${LXC_NAME}" 2>&1 | tee /tmp/ks-reconf-lxc.log
assert_mount_cephfs_idempotent /tmp/ks-reconf-lxc.log
test "$(ssh ${NODE} "grep -cE '^mp[0-9]+: .*,mp=/mnt/sn' /etc/pve/lxc/${lxc_vmid}.conf")" -eq 1

# Cleanup via pmx: entity, host mount, fstab line, directory and secret all go
uv run pmx destroy "${LXC_NAME}" --yes
ssh ${NODE} "! ceph auth get client.${LXC_NAME} >/dev/null 2>&1"
ssh ${NODE} "! findmnt ${HOST_MNT} >/dev/null 2>&1"
ssh ${NODE} "! test -e /mnt/pmx-passthrough/${LXC_NAME}"
ssh ${NODE} "! test -e /etc/pve/priv/ceph/pmx-${LXC_NAME}.secret"
ssh ${NODE} "! grep -q 'pmx-passthrough/${LXC_NAME}/' /etc/fstab"

echo "=== Kitchen-sink LXC passed all checks ==="
