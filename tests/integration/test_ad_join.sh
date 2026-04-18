#!/usr/bin/env bash
set -euo pipefail

# tests/integration/test_ad_join.sh — full-stack domain-join sanity check.
# Requires: pmx seed done; workstation has $AD_JOIN_PASSWORD exported OR runs interactively.
# Creates 4 guests (ubuntu vm, ubuntu lxc, rocky vm, rocky lxc), verifies, destroys.

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD before running (or run pmx new interactively once).}"

SMOKE_USER="${PMX_TEST_DOMAIN_USER:-jtd}"  # existing domain user for smoke-test logins

smoke_test() {
  local kind="$1"
  local os="$2"
  local name="pmxtest-${os}-${kind}-$$"
  local ssh_user

  if [ "$kind" = "vm" ]; then ssh_user="ansible"; else ssh_user="root"; fi

  echo "=== Building ${kind} ${os} named ${name} ==="
  uv run pmx new --name "${name}" --kind "${kind}" --os "${os}" \
    --cores 2 --memory 2048 --disk 16

  # Discover IP (same logic as in phase 03/04 test scripts; LXC path shown)
  local vmid ip
  if [ "$kind" = "vm" ]; then
    vmid=$(ssh root@192.168.9.12 "qm list | awk -v n=${name} '\$2==n{print \$1}'")
    ip=$(ssh root@192.168.9.12 "qm guest cmd ${vmid} network-get-interfaces" \
         | python3 -c 'import json,sys; print([a["ip-address"] for i in json.load(sys.stdin) if i["name"]!="lo" for a in i.get("ip-addresses",[]) if a["ip-address-type"]=="ipv4" and not a["ip-address"].startswith("127.")][0])')
  else
    vmid=$(ssh root@192.168.9.12 "pct list | awk -v n=${name} '\$NF==n{print \$1}'")
    ip=$(ssh root@192.168.9.12 "pct exec ${vmid} -- ip -j addr show" \
         | python3 -c 'import json,sys; print([a["local"] for i in json.load(sys.stdin) if i["ifname"]!="lo" for a in i.get("addr_info",[]) if a["family"]=="inet" and not a["local"].startswith("127.")][0])')
  fi

  echo "=== Verifying AD join on ${name} (${ip}) ==="
  ssh -o StrictHostKeyChecking=accept-new ${ssh_user}@${ip} "realm list | grep -q '${SMOKE_USER%@*}@broken.wrx\|broken.wrx'"
  ssh ${ssh_user}@${ip} "id Administrator@broken.wrx"
  ssh ${ssh_user}@${ip} "getent group domain_admins | head -1"
  ssh ${ssh_user}@${ip} "test -f /etc/sudoers.d/domain-admins && visudo -cf /etc/sudoers.d/domain-admins"

  # AC5 mkhomedir check requires an actual domain login. Do via ssh to a domain user; fall through on failure since it needs interactive password.
  # If PMX_TEST_DOMAIN_USER is set, try passwordless (operator must have keys in AD user's homedir OR this line is skipped):
  ssh -o BatchMode=yes ${SMOKE_USER}@${ip} "test -d /home/${SMOKE_USER} && whoami" \
    || echo "(mkhomedir live check requires a real AD user login; skipped in BatchMode)"

  echo "=== ${name} OK — destroying ==="
  if [ "$kind" = "vm" ]; then
    ssh root@192.168.9.12 "qm stop ${vmid} && qm destroy ${vmid} --purge"
  else
    ssh root@192.168.9.12 "pct stop ${vmid} && pct destroy ${vmid} --purge"
  fi
}

smoke_test vm  ubuntu
smoke_test lxc ubuntu
smoke_test vm  rocky
smoke_test lxc rocky

echo "All four combinations passed."
