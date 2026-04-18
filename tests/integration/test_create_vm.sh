#!/usr/bin/env bash
set -euo pipefail

# tests/integration/test_create_vm.sh — exercises pmx new --kind vm end-to-end.
#
# WARNING: DESTRUCTIVE
# This script creates real VMs on the Proxmox cluster.
# Requires: pmx seed already run (templates 9000 + 9001 exist).
# Leaves one VM per OS family running on the cluster; caller must clean up.
#
# Cleanup (when ready):
#   ssh root@192.168.9.12 "for n in pmxtest-ubuntu-* pmxtest-rocky-*; do vmid=\$(qm list | awk -v n=\$n '\$2==n{print \$1}'); [ -n \"\$vmid\" ] && qm stop \$vmid && qm destroy \$vmid --purge; done"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

smoke_test() {
  local os="$1"
  local name="pmxtest-${os}-$$"

  echo "=== Building ${os} VM named ${name} ==="
  AD_JOIN_PASSWORD=x uv run pmx new \
    --name "${name}" \
    --kind vm \
    --os "${os}" \
    --cores 2 --memory 2048 --disk 32 \
    --no-domain

  echo "=== Verifying ${name} ==="
  # Find IP via the state log (Phase 8) OR via pvesh once it exists; for Phase 3 we
  # rediscover via the cluster:
  local ip
  ip="$(ssh root@192.168.9.12 "qm guest cmd \$(qm list | awk -v n=${name} '\$2==n{print \$1}') network-get-interfaces" \
        | python3 -c 'import json,sys; print([a["ip-address"] for i in json.load(sys.stdin) if i["name"]!="lo" for a in i.get("ip-addresses",[]) if a["ip-address-type"]=="ipv4" and not a["ip-address"].startswith("127.")][0])')"

  echo "IP: ${ip}"

  ssh -o StrictHostKeyChecking=accept-new ansible@${ip} "systemctl is-active qemu-guest-agent"
  ssh ansible@${ip} "which tmux && which curl && which python3"

  echo "=== ${name} OK ==="
}

smoke_test ubuntu
smoke_test rocky
echo "Both OS families passed."
