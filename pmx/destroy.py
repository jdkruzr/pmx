"""pmx destroy — remove AD computer object, DNS records, and Proxmox resource."""

# FCIS: imperative shell

from __future__ import annotations

import json
import subprocess

import click

from pmx.ansible_runner import run_playbook
from pmx.config import load
from pmx.state import find_by_name, tombstone


def run(name: str, yes: bool) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)

    # Authoritative vmid + kind + hosting node from the cluster. The guest may
    # live on any node, not just cfg.default_node, so we target the node that
    # actually hosts it.
    cluster = _query_cluster(cfg.proxmox_ssh_host)
    if name not in cluster:
        click.echo(f"No guest named {name!r} found on the cluster.", err=True)
        return 1
    vmid, kind, node = cluster[name]

    # Whether to run DC-side AD/DNS dereg. A guest absent from the state log
    # wasn't created by pmx, so we can't know if it's domain-joined — attempt the
    # dereg anyway: dc_dereg.sh is idempotent and no-ops when there's nothing to
    # remove (and self-resolves the IP from the A record). A guest we KNOW is
    # non-domain (state says so) is skipped.
    if state is None:
        click.echo(
            f"Warning: {name} is not in {cfg.state_log_path} (not pmx-managed). "
            f"Will attempt DC-side dereg idempotently — it no-ops if there is "
            f"nothing to remove.",
            err=True,
        )
        maybe_joined = True
    else:
        maybe_joined = state.domain_joined
        if not maybe_joined:
            click.echo(
                f"{name} is not domain-joined; skipping AD/DNS deregistration.",
                err=True,
            )

    if not yes:
        click.confirm(
            f"Destroy {kind} {name} (vmid {vmid}) on node {node}"
            f"{' and remove its AD/DNS records' if maybe_joined else ''}?",
            abort=True,
        )

    if maybe_joined and not cfg.dc_ssh_host:
        click.echo(
            "Warning: dc_ssh_host is not set in config; skipping AD/DNS "
            "deregistration. The guest's computer object and DNS records will be "
            "left behind. Set dc_ssh_host to enable DC-side cleanup.",
            err=True,
        )

    extra_vars = {
        "target_node": node,
        "guest_name": name,
        "guest_vmid": vmid,
        "guest_kind": kind,
        "guest_ip": state.ip if state else None,
        "domain_join": maybe_joined and bool(cfg.dc_ssh_host),
        "ad_domain": cfg.ad_domain,
        "dc_ssh_host": cfg.dc_ssh_host,
    }
    rc = run_playbook("destroy.yml", extra_vars)

    # On a clean teardown, tombstone the guest in the state log so it stops
    # reading as live. The log is append-only, so this appends a tombstone of the
    # last live record rather than rewriting anything; it no-ops for a guest pmx
    # never tracked. A failed destroy leaves the record live so a retry still
    # sees it.
    if rc == 0:
        if tombstone(cfg.state_log_path, name) is not None:
            click.echo(f"Marked {name} destroyed in the state log.")

    return rc


def _query_cluster(ssh_host: str) -> dict[str, tuple[int, str, str]]:
    """Return {name: (vmid, kind, node)} for every guest across the cluster.

    Uses `pvesh get /cluster/resources --type vm`, which enumerates qemu VMs and
    lxc containers on ALL nodes (unlike `qm list`/`pct list`, which are
    local-node only) — so destroy can target whichever node hosts the guest.
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
