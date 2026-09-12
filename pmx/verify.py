"""pmx verify — live smoke test against a domain-joined guest."""

# FCIS: imperative shell

from __future__ import annotations

import json
import subprocess

import click

from pmx.cluster import query_cluster
from pmx.config import load
from pmx.state import find_by_name

_SSH_OPTS = [
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
]


def run(name: str) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)
    if state is None:
        click.echo(f"No record of {name} in {cfg.state_log_path}.", err=True)
        return 2

    ssh_user = "ansible" if state.kind == "vm" else "root"
    host = f"{ssh_user}@{state.ip}"

    # The sudoers drop-in lives under /etc/sudoers.d (0750, root-only) and is itself
    # 0440 root, so reading/validating it needs root. VMs connect as the
    # unprivileged `ansible` user (passwordless sudo set up at provision); LXCs
    # already connect as root.
    sudo = "" if ssh_user == "root" else "sudo "

    # Check ordering: sssd active, then id lookup. Keeps failure messages specific.
    # Each check is (label, ssh target, remote command, failure message).
    checks = [
        ("sssd is active", host, "systemctl is-active sssd", "sssd not active (AC14.2)"),
        (
            f"id Administrator@{cfg.ad_domain}",
            host,
            f"id Administrator@{cfg.ad_domain}",
            "Cannot resolve Administrator@" + cfg.ad_domain + " (AC14.3)",
        ),
        (
            "sudoers drop-in validates",
            host,
            (
                f"{sudo}test -f /etc/sudoers.d/domain-admins && "
                f"{sudo}/usr/sbin/visudo -cf /etc/sudoers.d/domain-admins"
            ),
            "sudoers drop-in missing or invalid",
        ),
    ]

    if state.cephfs_mounts:
        rc = _check_cephx_caps(cfg.proxmox_ssh_host, name, state.cephfs_mounts)
        if rc != 0:
            return rc
        checks.extend(_cephfs_mount_checks(cfg, name, state.kind, host, state.cephfs_mounts))

    for label, target, remote_cmd, err_msg in checks:
        result = subprocess.run(
            ["ssh", *_SSH_OPTS, target, remote_cmd], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            click.echo(f"[FAIL] {label}: {err_msg}", err=True)
            click.echo(result.stderr, err=True)
            return 1
        click.echo(f"[ OK ] {label}")

    click.echo(f"{name}: healthy.")
    return 0


def _check_cephx_caps(proxmox_ssh_host: str, name: str, mounts: list[str]) -> int:
    """Confirm `client.<name>` exists and its MDS caps cover every requested subpath."""
    entity = f"client.{name}"
    label = f"cephx caps for {entity}"
    result = subprocess.run(
        ["ssh", *_SSH_OPTS, proxmox_ssh_host, f"ceph auth get {entity} -f json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        click.echo(f"[FAIL] {label}: entity missing from the Ceph auth database", err=True)
        click.echo(result.stderr, err=True)
        return 1
    try:
        mds_caps = json.loads(result.stdout)[0]["caps"]["mds"]
    except (ValueError, KeyError, IndexError, TypeError):
        click.echo(f"[FAIL] {label}: could not parse `ceph auth get -f json` output", err=True)
        return 1

    missing = _uncovered_subpaths(mds_caps, [_parse_cephfs_spec(m)[0] for m in mounts])
    if missing:
        click.echo(
            f"[FAIL] {label}: mds caps {mds_caps!r} do not cover {', '.join(missing)}",
            err=True,
        )
        return 1
    click.echo(f"[ OK ] {label}")
    return 0


def _cephfs_mount_checks(
    cfg, name: str, kind: str, guest_host: str, mounts: list[str]
) -> list[tuple[str, str, str, str]]:
    """One `findmnt` identity check per mount: the live mount must be `name=<guest>`.

    VMs mount CephFS themselves. LXCs get a host-side mount on their node under
    /mnt/pmx-passthrough/<name>/<subpath> and a bind into the container, so the
    identity check runs on the node.
    """
    checks = []
    if kind == "vm":
        for spec in mounts:
            _, dest = _parse_cephfs_spec(spec)
            checks.append((
                f"cephfs {dest} mounted as {name}",
                guest_host,
                _findmnt_identity_cmd(dest, name),
                f"{dest} is not a CephFS mount authenticated as client.{name}",
            ))
        return checks

    cluster = query_cluster(cfg.proxmox_ssh_host)
    if name not in cluster:
        return checks
    _, _, node = cluster[name]
    for spec in mounts:
        subpath, dest = _parse_cephfs_spec(spec)
        host_path = f"/mnt/pmx-passthrough/{name}{subpath}"
        checks.append((
            f"cephfs {dest} (host {host_path}) mounted as {name}",
            cfg.proxmox_ssh_host,
            f"ssh -o BatchMode=yes {node} {_findmnt_identity_cmd(host_path, name)!r}",
            f"{host_path} on {node} is not a CephFS mount authenticated as client.{name}",
        ))
    return checks


def _findmnt_identity_cmd(path: str, name: str) -> str:
    return f"findmnt -rn -t ceph -o OPTIONS {path} | tr ',' '\\n' | grep -qx name={name}"


def _parse_cephfs_spec(spec: str) -> tuple[str, str]:
    """Mirror of the Ansible `pmx_parse_cephfs` filter: '<subpath>:<dest>' -> (subpath, dest)."""
    subpath, dest = spec.split(":", 1)
    if not subpath.startswith("/"):
        subpath = "/" + subpath
    return subpath, dest


def _uncovered_subpaths(mds_caps: str, subpaths: list[str]) -> list[str]:
    """Subpaths not granted by an MDS caps string of the form `fs authorize` writes.

    `allow rw fsname=cephfs` (no path=) covers everything; `path=/x` covers `/x`
    and anything beneath it.
    """
    granted: list[str] = []
    for clause in mds_caps.split(","):
        clause = clause.strip()
        if not clause.startswith("allow"):
            continue
        path = next((tok[len("path="):] for tok in clause.split() if tok.startswith("path=")), "/")
        granted.append(path.rstrip("/") or "/")
    missing = []
    for sub in subpaths:
        norm = sub.rstrip("/") or "/"
        if not any(g == "/" or norm == g or norm.startswith(g + "/") for g in granted):
            missing.append(sub)
    return missing
