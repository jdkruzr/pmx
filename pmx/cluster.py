"""Cluster-wide guest lookup shared across pmx commands.

A guest can live on any node of the Proxmox cluster, not just the configured
default. Commands that act on an existing guest (destroy, reconfigure) discover
its hosting node here rather than assuming `default_node`.
"""

# FCIS: imperative shell

from __future__ import annotations

import json
import subprocess

import click


def query_cluster(ssh_host: str) -> dict[str, tuple[int, str, str]]:
    """Return {name: (vmid, kind, node)} for every guest across the cluster.

    Uses `pvesh get /cluster/resources --type vm`, which enumerates qemu VMs and
    lxc containers on ALL nodes (unlike `qm list`/`pct list`, which are
    local-node only) — so a command can target whichever node hosts the guest.
    """
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        ssh_host,
        "pvesh get /cluster/resources --type vm --output-format json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=20)
    except subprocess.CalledProcessError as exc:
        click.echo(f"Failed to query Proxmox: {exc.stderr}", err=True)
        raise click.Abort() from exc
    except subprocess.TimeoutExpired as exc:
        click.echo(f"Timed out querying Proxmox ({ssh_host}).", err=True)
        raise click.Abort() from exc

    try:
        resources = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        click.echo(f"Could not parse Proxmox cluster resources: {exc}", err=True)
        raise click.Abort() from exc

    guests: dict[str, tuple[int, str, str]] = {}
    for r in resources:
        name = r.get("name")
        vmid = r.get("vmid")
        node = r.get("node")
        rtype = r.get("type")  # "qemu" or "lxc"
        if not name or vmid is None or not node or rtype not in ("qemu", "lxc"):
            continue
        kind = "vm" if rtype == "qemu" else "lxc"
        guests[name] = (int(vmid), kind, node)
    return guests
