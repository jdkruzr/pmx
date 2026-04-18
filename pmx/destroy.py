"""pmx destroy — remove AD computer object and destroy Proxmox resource."""

# FCIS: imperative shell

from __future__ import annotations

import subprocess

import click

from pmx.ansible_runner import run_playbook
from pmx.config import load
from pmx.credentials import ensure_ad_password
from pmx.state import find_by_name


def run(name: str, yes: bool) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)

    # Look up vmid + kind via the cluster directly (authoritative).
    cluster = _query_cluster(cfg.proxmox_ssh_host)
    if name not in cluster:
        click.echo(f"No guest named {name!r} found on the cluster.", err=True)
        return 1
    vmid, kind = cluster[name]

    if state is None:
        click.echo(
            f"Warning: {name} is not in {cfg.state_log_path}. "
            f"Proceeding with destroy but skipping AD computer object cleanup.",
            err=True,
        )
        domain_joined = False
    else:
        domain_joined = state.domain_joined

    if not yes:
        click.confirm(
            f"Destroy {kind} {name} (vmid {vmid})"
            f"{' and remove AD computer object' if domain_joined else ''}?",
            abort=True,
        )

    if domain_joined:
        ensure_ad_password()

    extra_vars = {
        "target_node": cfg.default_node,
        "guest_name": name,
        "guest_vmid": vmid,
        "guest_kind": kind,
        "guest_ip": state.ip if state else None,
        "domain_join": domain_joined,
        "ad_domain": cfg.ad_domain,
        "ad_join_user": cfg.ad_join_user,
    }
    return run_playbook("destroy.yml", extra_vars)


def _query_cluster(ssh_host: str) -> dict[str, tuple[int, str]]:
    """Return {name: (vmid, kind)} discovered via ssh qm list + pct list."""
    cmd = ["ssh", "-o", "BatchMode=yes", ssh_host, "qm list; echo ---; pct list"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
    guests: dict[str, tuple[int, str]] = {}
    kind = "vm"
    for line in result.stdout.splitlines():
        if line.strip() == "---":
            kind = "lxc"
            continue
        parts = line.split()
        if not parts or parts[0] in ("VMID", "---"):
            continue
        try:
            vmid = int(parts[0])
        except ValueError:
            continue
        # qm list: VMID NAME ...
        # pct list: VMID STATUS LOCK NAME (older) or VMID STATUS NAME (newer)
        if kind == "vm":
            guests[parts[1]] = (vmid, "vm")
        else:
            guests[parts[-1]] = (vmid, "lxc")
    return guests
