#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
source "${REPO_ROOT}/tests/integration/_guard.sh"

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
            "static_gw","cephx_entity","created_at","destroyed_at"}
missing = expected - set(rec.keys())
assert not missing, f"missing fields: {missing}"
assert rec["hostname"] == "${NAME1}", rec
assert rec["kind"] == "lxc", rec
assert rec["os"] == "ubuntu", rec
assert rec["domain_joined"] is False, rec
assert rec["destroyed_at"] == "", rec  # live on creation
assert rec["cephx_entity"] == "", rec  # no --cephfs, so no CephX identity minted
PY

# AC15.2 — second build appends, first record preserved
NAME2="pmxtest-state2-$$"
uv run pmx new --name "${NAME2}" --kind lxc --os rocky --no-domain \
  --cores 1 --memory 512 --disk 8

line_count=$(wc -l < "${LOG}")
test "${line_count}" -eq 2
grep -q "\"hostname\": \"${NAME1}\"" "${LOG}"  # first line preserved
grep -q "\"hostname\": \"${NAME2}\"" "${LOG}"

# AC15.4 — destroy tombstones the guest. The log is append-only, so each destroy
# appends a tombstone (a copy of the last live record with destroyed_at stamped)
# rather than rewriting the file; the destroyed guest then reads as absent.
uv run pmx destroy "${NAME1}" --yes
uv run pmx destroy "${NAME2}" --yes

line_count=$(wc -l < "${LOG}")
test "${line_count}" -eq 4  # 2 live + 2 tombstones, nothing rewritten

python3 - <<PY
import json
recs = [json.loads(line) for line in open("${LOG}")]
for nm in ("${NAME1}", "${NAME2}"):
    hist = [r for r in recs if r["hostname"] == nm]
    assert len(hist) == 2, (nm, len(hist))
    live, stone = hist
    assert live["destroyed_at"] == "", (nm, live)
    assert stone["destroyed_at"], f"{nm} newest record is not a tombstone: {stone}"
    # Tombstone preserves the guest's final identity for audit.
    assert stone["vmid"] == live["vmid"], (nm, live, stone)
    assert stone["ip"] == live["ip"], (nm, live, stone)
PY

# find_by_name now reads both as absent (destroyed).
python3 - <<PY
from pmx.config import load
from pmx.state import find_by_name
cfg = load()
assert find_by_name(cfg.state_log_path, "${NAME1}") is None
assert find_by_name(cfg.state_log_path, "${NAME2}") is None
PY

echo "State log tests passed."
