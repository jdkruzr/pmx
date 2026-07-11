#!/usr/bin/env bash
# pmx DC-side registration — run ON the Samba AD DC (galactica), as root.
#
# Authoritatively registers a new guest's forward + reverse DNS using the
# canonical local tooling, where it lives. This does NOT rely on the guest's own
# SSSD dynamic DNS, which (a) races on the forward zone — so the A landed only
# sometimes — and (b) structurally CANNOT update the reverse zone at all: the
# reverse zone is a classic BIND master, updated by the local session key
# (nsupdate -l), not by a machine's GSS-TSIG update to the AD DNS. Hence the PTR
# never registered. Doing both here, on the DC, makes registration deterministic:
#   - forward A  (Samba AD/DLZ forward zone)  -> samba-tool dns   (machine acct, -P)
#   - reverse PTR (classic BIND master zone)  -> nsupdate -l      (BIND session key)
#
# Running on the DC against the local databases needs no Kerberos password. Every
# step is idempotent: re-running replaces the record in place (mirrors dc_dereg.sh,
# so register/reconfigure/destroy all converge).
#
#   ssh <dc> sudo bash -s -- <name> <domain> <ip> < dc_reg.sh
set -u

name="${1:-}"
domain="${2:-}"
ip="${3:-}"

if [ -z "$name" ] || [ -z "$domain" ] || [ -z "$ip" ]; then
  echo "usage: dc_reg.sh <name> <domain> <ip>" >&2
  exit 2
fi
if ! printf '%s' "$ip" | grep -qE '^[0-9]+(\.[0-9]+){3}$'; then
  echo "dc_reg.sh: '$ip' is not an IPv4 address" >&2
  exit 2
fi

fqdn="$name.$domain"

# 1) Forward A (Samba AD/DLZ). Idempotent + self-correcting: skip if it already
#    matches, update in place if the name resolves to a different IP (a rebuilt
#    host reusing the name), otherwise add. samba-tool dns add errors if the exact
#    record already exists, so we branch on the current value rather than blindly
#    adding. stderr carries only GENSEC backend chatter, so it's dropped.
cur="$(samba-tool dns query localhost "$domain" "$name" A -P 2>/dev/null \
       | grep -oE 'A: [0-9.]+' | awk '{print $2}' | head -1)"
if [ "$cur" = "$ip" ]; then
  echo "[dns]  A    $fqdn -> $ip already present"
elif [ -n "$cur" ]; then
  if samba-tool dns update localhost "$domain" "$name" A "$cur" "$ip" -P >/dev/null 2>&1; then
    echo "[dns]  updated A    $fqdn: $cur -> $ip"
  else
    echo "[dns]  A update reported an error (non-fatal)"
  fi
else
  if samba-tool dns add localhost "$domain" "$name" A "$ip" -P >/dev/null 2>&1; then
    echo "[dns]  added A    $fqdn -> $ip"
  else
    echo "[dns]  A add reported an error (non-fatal)"
  fi
fi

# 2) Reverse PTR (classic BIND zone) via the local session key. "delete then add"
#    is idempotent — it replaces any stale PTR for this IP in one transaction.
#    Some nsupdate builds emit a cosmetic '::1 ... operation canceled' line (named
#    binds 127.0.0.1) but still succeed over IPv4 — hence stderr is dropped.
rev="$(printf '%s' "$ip" | awk -F. '{print $4"."$3"."$2"."$1".in-addr.arpa"}')"
if printf 'update delete %s. PTR\nupdate add %s. 3600 PTR %s.\nsend\n' "$rev" "$rev" "$fqdn" \
     | nsupdate -l 2>/dev/null; then
  echo "[dns]  PTR  $rev -> $fqdn"
else
  echo "[dns]  PTR add reported an error (non-fatal)"
fi

exit 0
