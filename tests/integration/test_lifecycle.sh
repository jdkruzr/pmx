#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD first.}"

NAME="pmxtest-lifecycle-$$"

echo "=== Create ${NAME} (Ubuntu VM, domain-joined) ==="
uv run pmx new --name "${NAME}" --kind vm --os ubuntu \
  --cores 2 --memory 2048 --disk 16

echo "=== Verify — expect exit 0 (AC14.1) ==="
uv run pmx verify "${NAME}"

echo "=== Reconfigure — first run, should be no-op but exit 0 (AC13.1, AC13.2) ==="
uv run pmx reconfigure "${NAME}"

echo "=== Reconfigure again — still a no-op ==="
uv run pmx reconfigure "${NAME}"

echo "=== Destroy — confirm via --yes (AC12.1) ==="
uv run pmx destroy "${NAME}" --yes

echo "=== Post-destroy: verify vmid is gone ==="
vmid_probe=$(ssh root@192.168.9.12 "qm list | awk -v n=${NAME} '\$2==n{print \$1}'")
if [ -n "${vmid_probe}" ]; then
  echo "BUG: ${NAME} still in qm list after destroy"
  exit 1
fi

echo "=== AC12.2 — build with --no-domain, verify destroy skips adcli ==="
NONAD="pmxtest-nodomain-$$"
uv run pmx new --name "${NONAD}" --kind lxc --os ubuntu --no-domain \
  --cores 1 --memory 512 --disk 8
uv run pmx destroy "${NONAD}" --yes 2>&1 | tee /tmp/destroy.log
grep -q "skipping AD computer object cleanup" /tmp/destroy.log

echo "=== AC12.3 — destroy a guest not in state log ==="
# Create a guest by hand via pct using the Rocky LXC template that `pmx seed`
# guarantees is present (Ubuntu LXC templates are NOT fetched by seed, so we
# can't assume they exist here). Then destroy via pmx; expect warning + clean destroy.
ORPHAN="pmxtest-orphan-$$"
ssh root@192.168.9.12 "pct create \$(pvesh get /cluster/nextid) \
  cephfs:vztmpl/\$(pveam list cephfs | grep -oE 'rockylinux-9-default_[^ ]+' | head -1) \
  --hostname ${ORPHAN} --memory 256 --rootfs cephfs:1 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1"
uv run pmx destroy "${ORPHAN}" --yes 2>&1 | tee /tmp/destroy2.log
grep -q "not in" /tmp/destroy2.log

echo "All lifecycle tests passed."
