#!/usr/bin/env bash
# pmx DC-side deregistration — run ON the Samba AD DC (galactica), as root.
#
# Removes a destroyed guest's three lingering identities using the canonical
# local tooling, where it lives:
#   - forward A  (Samba AD/DLZ forward zone)  -> samba-tool dns   (machine acct, -P)
#   - reverse PTR (classic BIND master zone)  -> nsupdate -l      (BIND session key)
#   - AD computer object (local sam.ldb)      -> samba-tool computer
#
# Running on the DC against the local databases means no Kerberos password is
# needed and it works even when the guest is already powered off. Every step is
# idempotent and non-fatal: a missing record/object must never block a teardown.
#
# Invoked over ssh, script on stdin, three positional args:
#   ssh <dc> sudo bash -s -- <name> <ip> <domain> < dc_dereg.sh
set -u

name="${1:-}"
ip="${2:-}"
domain="${3:-}"

if [ -z "$name" ] || [ -z "$domain" ]; then
  echo "usage: dc_dereg.sh <name> <ip> <domain>" >&2
  exit 2
fi

# 1) Forward A (Samba AD/DLZ). samba-tool dns delete is NOT idempotent — it
#    errors with a traceback if the record is already gone — so query-guard it.
if samba-tool dns query localhost "$domain" "$name" A -P >/dev/null 2>&1; then
  if [ -n "$ip" ]; then
    if samba-tool dns delete localhost "$domain" "$name" A "$ip" -P >/dev/null 2>&1; then
      echo "[dns]  deleted A    $name.$domain -> $ip"
    else
      echo "[dns]  A delete reported an error (non-fatal)"
    fi
  else
    echo "[dns]  A present but no IP supplied; left in place"
  fi
else
  echo "[dns]  A    $name.$domain already absent"
fi

# 2) Reverse PTR (classic BIND zone) via the local session key. nsupdate
#    delete-of-absent is a clean no-op, so no guard is needed. Some nsupdate
#    builds emit a cosmetic '::1 ... operation canceled' line (named binds
#    127.0.0.1) but still succeed over IPv4 — hence stderr is dropped.
if printf '%s' "$ip" | grep -qE '^[0-9]+(\.[0-9]+){3}$'; then
  rev="$(printf '%s' "$ip" | awk -F. '{print $4"."$3"."$2"."$1".in-addr.arpa"}')"
  if printf 'update delete %s. PTR\nsend\n' "$rev" | nsupdate -l 2>/dev/null; then
    # nsupdate delete succeeds whether or not the record existed, so this is an
    # "ensured absent", not a confirmed removal.
    echo "[dns]  PTR  $rev  ensured absent"
  else
    echo "[dns]  PTR delete reported an error (non-fatal)"
  fi
fi

# 3) AD computer object (local sam.ldb). Guard with `computer list` so a re-run
#    is a clean no-op rather than a non-zero error.
if samba-tool computer list 2>/dev/null | grep -qiFx "${name}\$"; then
  if samba-tool computer delete "$name" >/dev/null 2>&1; then
    echo "[ad]   deleted computer object ${name}\$"
  else
    echo "[ad]   computer-object delete reported an error (non-fatal)"
  fi
else
  echo "[ad]   computer object ${name}\$ already absent"
fi

exit 0
