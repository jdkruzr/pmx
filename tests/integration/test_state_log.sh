#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

: "${AD_JOIN_PASSWORD:?Export AD_JOIN_PASSWORD first.}"

LOG="${REPO_ROOT}/state/guests.jsonl"

# AC15.3 — log missing, first build creates it
rm -f "${LOG}"

NAME1="pmxtest-state1-$$"
uv run pmx new --name "${NAME1}" --kind lxc --os ubuntu --no-domain \
  --cores 1 --memory 512 --disk 8

test -f "${LOG}"
line_count=$(wc -l < "${LOG}")
test "${line_count}" -eq 1

# AC15.1 — record has all expected fields
python3 - <<PY
import json, sys
rec = json.loads(open("${LOG}").readline())
expected = {"hostname","vmid","mac","ip","kind","os","domain_joined",
            "cephfs_mounts","rbd_disk","extra_packages","static_ip",
            "static_gw","created_at"}
missing = expected - set(rec.keys())
assert not missing, f"missing fields: {missing}"
assert rec["hostname"] == "${NAME1}", rec
assert rec["kind"] == "lxc", rec
assert rec["os"] == "ubuntu", rec
assert rec["domain_joined"] is False, rec
PY

# AC15.2 — second build appends, first record preserved
NAME2="pmxtest-state2-$$"
uv run pmx new --name "${NAME2}" --kind lxc --os rocky --no-domain \
  --cores 1 --memory 512 --disk 8

line_count=$(wc -l < "${LOG}")
test "${line_count}" -eq 2
grep -q "\"hostname\": \"${NAME1}\"" "${LOG}"  # first line preserved
grep -q "\"hostname\": \"${NAME2}\"" "${LOG}"

# Cleanup
uv run pmx destroy "${NAME1}" --yes
uv run pmx destroy "${NAME2}" --yes

echo "State log tests passed."
