"""Preflight checks for pmx (name uniqueness, SSH reachability).

FCIS: imperative shell
"""

from __future__ import annotations

import subprocess

import click

from pmx.config import Config


def assert_name_available(cfg: Config, name: str) -> None:
    """Abort if a VM or LXC with the given name already exists on the cluster."""
    # Validate name matches ^[a-zA-Z0-9][a-zA-Z0-9-]*$ (alphanumeric + hyphens, must start with alphanumeric)
    import re
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$", name):
        click.echo(
            f"Invalid guest name '{name}'. Names must start with alphanumeric and "
            f"contain only alphanumeric characters and hyphens.",
            err=True,
        )
        raise click.Abort()

    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        cfg.proxmox_ssh_host,
        "qm list; echo '---'; pct list",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        click.echo(f"Failed to query Proxmox: {exc.stderr}", err=True)
        raise click.Abort() from exc
    except subprocess.TimeoutExpired as exc:
        click.echo(f"Timed out querying Proxmox ({cfg.proxmox_ssh_host}).", err=True)
        raise click.Abort() from exc

    existing = _parse_names(result.stdout)
    if name in existing:
        click.echo(
            f"A guest named '{name}' already exists on the cluster. "
            f"Names are the primary key for pmx; choose a different name or destroy the existing one.",
            err=True,
        )
        raise click.Abort()


def _parse_names(qm_pct_output: str) -> set[str]:
    """Extract guest names from the output of `qm list; echo ---; pct list`.

    NOTE: This is a heuristic against pct list output and may need updating if Proxmox
    adds new container states. Current recognized status words: running, stopped, suspended,
    paused, mounted.
    """
    names: set[str] = set()
    in_qm_section = True  # Start with qm list section

    for line in qm_pct_output.splitlines():
        parts = line.split()
        # Skip empty lines and headers
        if not parts or parts[0] == "VMID":
            continue
        # Separator switches from qm to pct section
        if parts[0] == "---":
            in_qm_section = False
            continue

        # Try to parse VMID from first field (validates it's an int before processing)
        try:
            int(parts[0])
        except ValueError:
            continue

        # In qm list: VMID NAME STATUS ...
        # NAME is at index 1
        if in_qm_section and len(parts) > 1:
            names.add(parts[1])
        # In pct list: VMID STATUS [LOCK] NAME
        # Filter out numeric fields (LOCK column) and pure-status words (running/stopped/suspended/paused/mounted)
        # Take the last field that contains hyphens or is longer and not a status word
        elif not in_qm_section and len(parts) > 1:
            status_words = {"running", "stopped", "suspended", "paused", "mounted"}
            candidates = [
                p for p in parts[1:]
                if (p.replace("-", "").isalnum() and not p.isdigit() and p not in status_words)
            ]
            if candidates:
                names.add(candidates[-1])

    return names
