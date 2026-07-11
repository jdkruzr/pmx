#!/usr/bin/env bash
# pmx DC-side inspection (READ-ONLY) — run ON the Samba AD DC (galactica), as root.
#
# Reports what a destroy WOULD find and remove, changing nothing. It replicates
# dc_dereg.sh's resolution exactly, so `pmx destroy --dry-run` predicts precisely
# what the real teardown will do — including whether the AD computer object will
# auto-clean or need manual cleanup (the guest-name vs machine-account mismatch).
#
#   ssh <dc> sudo bash -s -- <name> <domain> [ip] < dc_inspect.sh
set -u

name="${1:-}"
domain="${2:-}"
ip="${3:-}"

if [ -z "$name" ] || [ -z "$domain" ]; then
  echo "usage: dc_inspect.sh <name> <domain> [ip]" >&2
  exit 2
fi

# Forward A (Samba AD/DLZ). stderr carries only GENSEC backend chatter -> drop.
a_ip="$(samba-tool dns query localhost "$domain" "$name" A -P 2>/dev/null \
        | grep -oE 'A: [0-9.]+' | awk '{print $2}' | head -1)"
if [ -n "$a_ip" ]; then
  echo "fwd A     : $name.$domain -> $a_ip"
else
  echo "fwd A     : (none)"
fi

# Reverse PTR (classic BIND zone). Use the supplied IP, else the A we just found
# (mirrors dc_dereg's self-resolution when the guest isn't in pmx state).
[ -z "$ip" ] && ip="$a_ip"
if printf '%s' "$ip" | grep -qE '^[0-9]+(\.[0-9]+){3}$'; then
  ptr="$(dig +short -x "$ip" @127.0.0.1 2>/dev/null | head -1)"
  if [ -n "$ptr" ]; then
    echo "rev PTR   : $ip -> $ptr"
  else
    echo "rev PTR   : $ip (none)"
  fi
else
  echo "rev PTR   : (no IP to check)"
fi

# AD computer object — replicate dc_dereg's resolution to predict auto-clean:
# dNSHostName first, then exact name. Read-only (no delete).
sam_ldb=/var/lib/samba/private/sam.ldb
acct="$(ldbsearch -H "$sam_ldb" "(dNSHostName=${name}.${domain})" sAMAccountName 2>/dev/null \
        | sed -n 's/^sAMAccountName: //p' | head -1)"
acct="${acct%\$}"
how=""
[ -n "$acct" ] && how="dNSHostName"
if [ -z "$acct" ] && samba-tool computer list 2>/dev/null | grep -qiFx "${name}\$"; then
  acct="$name"
  how="exact name"
fi
if [ -n "$acct" ]; then
  echo "AD object : ${acct}\$ (resolves by ${how} -> destroy WILL remove it)"
else
  echo "AD object : no match by dNSHostName or exact name -> destroy will NOT auto-remove"
  # Informational only: surface objects a mismatched hostname would orphan, e.g.
  # VM 'paperless-ngx' whose OS hostname was 'paperless' (account PAPERLESS$).
  token="${name%%-*}"
  if [ "${#token}" -ge 3 ]; then
    cands="$(samba-tool computer list 2>/dev/null | grep -iF "$token" | tr '\n' ' ')"
    [ -n "$cands" ] && echo "            hint: possibly-related object(s), manual cleanup: ${cands}"
  fi
fi

exit 0
