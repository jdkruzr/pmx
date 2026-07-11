# Sourced by the live integration tests in this directory. Those scripts create
# REAL guests on the Proxmox cluster (and join them to AD), so they must never
# run by accident — e.g. a blanket `for f in tests/integration/*.sh` or a CI
# sweep. They no-op with a clear message unless PMX_LIVE=1 is explicitly set.
#
# Usage: source right after `cd "$REPO_ROOT"`, before any other preconditions
# (so an un-opted run skips cleanly instead of erroring on a missing var):
#   source "${REPO_ROOT}/tests/integration/_guard.sh"
#
# Run one for real with:  PMX_LIVE=1 tests/integration/test_lifecycle.sh
if [ "${PMX_LIVE:-0}" != "1" ]; then
  echo "SKIP $(basename "${BASH_SOURCE[1]:-$0}"): creates real guests on the cluster; set PMX_LIVE=1 to run it." >&2
  exit 0
fi
