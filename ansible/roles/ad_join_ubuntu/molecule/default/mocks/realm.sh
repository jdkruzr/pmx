#!/usr/bin/env bash
# Stub out realm for molecule. Records joins; returns plausible `realm list` output.
set -e
case "${1:-}" in
  join)
    touch /var/run/realm-joined
    exit 0
    ;;
  list)
    if [ -f /var/run/realm-joined ]; then
      printf '%s\n  type: kerberos\n  realm-name: %s\n  domain-name: %s\n' \
        "${AD_DOMAIN:-test.example}" "${AD_REALM:-TEST.EXAMPLE}" "${AD_DOMAIN:-test.example}"
    fi
    exit 0
    ;;
  *)
    echo "mock realm: ${*}" >&2
    exit 0
    ;;
esac
