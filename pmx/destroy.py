"""pmx destroy — remove AD computer object, DNS records, and Proxmox resource."""

# FCIS: imperative shell

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from pmx.ansible_runner import run_playbook
from pmx.cluster import query_cluster
from pmx.config import load
from pmx.state import GuestRecord, find_by_name, tombstone

_DC_INSPECT = Path(__file__).resolve().parent.parent / "ansible" / "files" / "dc_inspect.sh"


def run(name: str, yes: bool, dry_run: bool = False) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)

    # Authoritative vmid + kind + hosting node from the cluster. The guest may
    # live on any node, not just cfg.default_node, so we target the node that
    # actually hosts it.
    cluster = query_cluster(cfg.proxmox_ssh_host)
    if name not in cluster:
        click.echo(f"No guest named {name!r} found on the cluster.", err=True)
        return 1
    vmid, kind, node = cluster[name]

    # Whether DC-side AD/DNS dereg applies. A guest absent from the state log
    # wasn't created by pmx, so we can't know if it's domain-joined — attempt the
    # dereg anyway (dc_dereg.sh is idempotent and self-resolves the IP). A guest
    # we KNOW is non-domain (state says so) is skipped.
    if state is None:
        maybe_joined = True
        state_status = "untracked (not pmx-managed)"
    else:
        maybe_joined = state.domain_joined
        state_status = "managed, domain-joined" if maybe_joined else "managed, not domain-joined"

    # Preflight: report exactly what a destroy would touch, change nothing.
    if dry_run:
        _print_preflight(cfg, name, vmid, kind, node, state, maybe_joined, state_status)
        return 0

    if state is None:
        click.echo(
            f"Warning: {name} is not in {cfg.state_log_path} (not pmx-managed). "
            f"Will attempt DC-side dereg idempotently — it no-ops if there is "
            f"nothing to remove.",
            err=True,
        )
    elif not maybe_joined:
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


def _print_preflight(
    cfg,
    name: str,
    vmid: int,
    kind: str,
    node: str,
    state: GuestRecord | None,
    maybe_joined: bool,
    state_status: str,
) -> None:
    """Print the read-only destroy plan. Touches nothing."""
    status = _cluster_status(cfg.proxmox_ssh_host, node, vmid, kind)
    click.echo(f"{name}  vmid {vmid}  {kind}  node {node}  {status}")
    click.echo(f"  state log : {state_status}")

    if not maybe_joined:
        click.echo("  DNS/AD    : not domain-joined — no records to remove")
        dereg = ""
    elif not cfg.dc_ssh_host:
        click.echo("  DNS/AD    : dc_ssh_host not set — cannot inspect or deregister")
        dereg = ""
    else:
        for line in _inspect_dc(cfg.dc_ssh_host, name, cfg.ad_domain, state.ip if state else ""):
            click.echo(f"  {line}")
        dereg = "deregister A/PTR + AD computer object, then "

    click.echo(f"Would {dereg}destroy {kind} {name} (vmid {vmid}) on {node}. No changes made.")


def _cluster_status(ssh_host: str, node: str, vmid: int, kind: str) -> str:
    """Best-effort running/stopped status for the guest (dry-run cosmetic)."""
    tool = "qm" if kind == "vm" else "pct"
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", ssh_host,
           f"ssh -o BatchMode=yes {node} {tool} status {vmid}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip().replace("status: ", "")


def _inspect_dc(dc_ssh_host: str, name: str, domain: str, ip: str) -> list[str]:
    """Run the read-only DC inspect script and return its report lines."""
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10", dc_ssh_host, "sudo", "bash", "-s", "--",
        name, domain, ip or "",
    ]
    try:
        with open(_DC_INSPECT) as script:
            result = subprocess.run(
                cmd, stdin=script, capture_output=True, text=True, timeout=20
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"DNS/AD    : inspection failed ({exc})"]
    lines = (result.stdout or "").splitlines()
    return lines or [f"DNS/AD    : no output from DC (rc={result.returncode})"]
