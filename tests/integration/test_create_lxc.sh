#!/usr/bin/env bash
set -euo pipefail

# tests/integration/test_create_lxc.sh — exercises pmx new --kind lxc end-to-end.
# Requires: pmx seed already run (Rocky LXC template present on cephfs).

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

smoke_test() {
  local os="$1"
  local name="pmxtest-lxc-${os}-$$"

  echo "=== Building ${os} LXC named ${name} ==="
  AD_JOIN_PASSWORD=x uv run pmx new \
    --name "${name}" \
    --kind lxc \
    --os "${os}" \
    --cores 1 --memory 1024 --disk 8 \
    --no-domain

  local vmid
  vmid=$(ssh root@192.168.9.12 "pct list | awk -v n=${name} '\$NF==n{print \$1}'")
  if [ -z "${vmid}" ]; then echo "VMID not found for ${name}"; exit 1; fi
  echo "VMID: ${vmid}"

  echo "=== Checking unprivileged-with-idmap ==="
  ssh root@192.168.9.12 "grep -c '^unprivileged: 1' /etc/pve/lxc/${vmid}.conf"  # expects 1
  ssh root@192.168.9.12 "grep -c '^lxc.idmap = u 500000000' /etc/pve/lxc/${vmid}.conf"  # expects 1
  ssh root@192.168.9.12 "pct exec ${vmid} -- cat /proc/self/uid_map" \
    | tee /dev/stderr \
    | grep -q "500000000 500000000 99999999"

  echo "=== Checking SSH reachability from workstation ==="
  local ip
  ip=$(ssh root@192.168.9.12 "pct exec ${vmid} -- ip -j addr show" \
        | python3 -c 'import json,sys; print([a["local"] for i in json.load(sys.stdin) if i["ifname"]!="lo" for a in i.get("addr_info",[]) if a["family"]=="inet" and not a["local"].startswith("127.")][0])')
  ssh -o StrictHostKeyChecking=accept-new root@${ip} "which tmux && which curl && which python3"

  echo "=== ${name} OK ==="
}

smoke_test ubuntu
smoke_test rocky
echo "Both LXC OS families passed."
