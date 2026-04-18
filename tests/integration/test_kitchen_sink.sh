#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD first.}"

NAME="pmxtest-kitchen-$$"

echo "=== Building kitchen-sink VM: ${NAME} ==="
uv run pmx new --name "${NAME}" --kind vm --os ubuntu \
  --cores 2 --memory 2048 --disk 32 \
  --cephfs supernote:/mnt/sn \
  --rbd-disk 10 \
  --extra-packages htop,jq \
  --static-ip 192.168.9.80/24 --static-gw 192.168.9.1

vmid=$(ssh root@192.168.9.12 "qm list | awk -v n=${NAME} '\$2==n{print \$1}'")
echo "VMID: ${vmid}"

# Verify extra disk attached (AC9.1)
ssh root@192.168.9.12 "qm config ${vmid} | grep -E '^scsi1:\s+bwrx:.+,size=10G'"

# Verify static IP (AC11.1)
ssh -o StrictHostKeyChecking=accept-new ansible@192.168.9.80 \
  "ip -4 addr show | grep -q 'inet 192.168.9.80/24'"

# Verify cephfs mount (AC8.1)
ssh ansible@192.168.9.80 "findmnt /mnt/sn | grep -q ceph"

# Verify extra packages (AC10.1)
ssh ansible@192.168.9.80 "which htop && which jq"

# Cleanup
ssh root@192.168.9.12 "qm stop ${vmid} && qm destroy ${vmid} --purge"

echo "=== Kitchen-sink VM passed all checks ==="

# Now the LXC variant (no --rbd-disk; LXC rejection was covered in Task 1 unit test).
LXC_NAME="pmxtest-kitchen-lxc-$$"

echo "=== Building kitchen-sink LXC: ${LXC_NAME} (NOTE: --static-gw deliberately omitted — exercises the .1-of-subnet inference path) ==="
uv run pmx new --name "${LXC_NAME}" --kind lxc --os rocky \
  --cores 1 --memory 1024 --disk 8 \
  --cephfs supernote:/mnt/sn \
  --extra-packages htop,jq \
  --static-ip 192.168.9.81/24

lxc_vmid=$(ssh root@192.168.9.12 "pct list | awk -v n=${LXC_NAME} '\$NF==n{print \$1}'")
echo "LXC VMID: ${lxc_vmid}"

# Verify LXC mp line exists (AC8.2, AC2.3)
ssh root@192.168.9.12 "grep -E '^mp[0-9]+:.*mp=/mnt/sn' /etc/pve/lxc/${lxc_vmid}.conf"

# Verify mount is visible inside container
ssh root@192.168.9.12 "pct exec ${lxc_vmid} -- findmnt /mnt/sn | grep -q /mnt/sn"

# Verify static IP on LXC (AC11.2)
ssh -o StrictHostKeyChecking=accept-new root@192.168.9.81 \
  "ip -4 addr show | grep -q 'inet 192.168.9.81/24'"

# Verify inferred gateway picked up the .1-of-subnet default (AC11.2, Critical 2 regression guard)
ssh root@192.168.9.81 "ip -4 route show default | grep -q '192.168.9.1'"

# Verify extra packages (AC10.1 on Rocky via dnf)
ssh root@192.168.9.81 "which htop && which jq"

# Cleanup
ssh root@192.168.9.12 "pct stop ${lxc_vmid} && pct destroy ${lxc_vmid} --purge"

echo "=== Kitchen-sink LXC passed all checks ==="
