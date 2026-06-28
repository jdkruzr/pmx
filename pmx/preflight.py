"""Preflight checks for pmx (name uniqueness, IP availability, SSH reachability).

FCIS: imperative shell
"""

from __future__ import annotations

import ipaddress
import re
import subprocess

import click

from pmx.config import Config


def assert_name_available(cfg: Config, name: str) -> None:
    """Abort if a VM or LXC with the given name already exists on the cluster."""
    # Validate name matches ^[a-zA-Z0-9][a-zA-Z0-9-]*$ (alphanumeric + hyphens, must start with alphanumeric)
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


def assert_ip_available(cfg: Config, static_ip: str | None) -> None:
    """Abort if the requested static IP is already allocated on the cluster.

    DHCP guests (``static_ip is None``) are skipped — they lease an address at
    boot. "Allocated" is judged by what is *declared* in guest configs
    (``ipconfig0`` for VMs, ``net0`` for LXC), which deliberately catches
    powered-off guests that still own their IP — a liveness probe would not.
    """
    if static_ip is None:
        return

    iface = ipaddress.ip_interface(static_ip)
    requested = iface.ip
    network = iface.network
    if requested in (network.network_address, network.broadcast_address):
        kind = "network" if requested == network.network_address else "broadcast"
        click.echo(
            f"{requested} is the {kind} address of {network}; not a usable host IP.",
            err=True,
        )
        raise click.Abort()

    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        cfg.proxmox_ssh_host,
        # /etc/pve is cluster-synced, so one node's view covers every guest's config.
        "cat /etc/pve/nodes/*/qemu-server/*.conf /etc/pve/nodes/*/lxc/*.conf 2>/dev/null || true",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        click.echo(f"Failed to query Proxmox: {exc.stderr}", err=True)
        raise click.Abort() from exc
    except subprocess.TimeoutExpired as exc:
        click.echo(f"Timed out querying Proxmox ({cfg.proxmox_ssh_host}).", err=True)
        raise click.Abort() from exc

    allocated = _parse_allocated_ips(result.stdout)
    if str(requested) in allocated:
        suggestion = _suggest_free_ip(static_ip, allocated)
        hint = f" Next free in {network}: {suggestion}." if suggestion else ""
        click.echo(
            f"IP {requested} is already allocated to a guest on the cluster "
            f"(declared in a guest config, including powered-off guests). "
            f"Choose a different address.{hint}",
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


def _parse_allocated_ips(config_text: str) -> set[str]:
    """Extract statically-declared IPv4 host addresses from Proxmox guest configs.

    Handles both VM cloud-init (``ipconfig0: ip=A.B.C.D/NN,gw=...``) and LXC
    (``net0: ...,ip=A.B.C.D/NN,...``) forms. ``ip=dhcp`` yields nothing. Only the
    ``ip=`` token is read (not ``gw=``), and the CIDR suffix is dropped.
    """
    ips: set[str] = set()
    for line in config_text.splitlines():
        if not re.match(r"(ipconfig\d+|net\d+):", line.strip()):
            continue
        for match in re.finditer(r"\bip=(\d{1,3}(?:\.\d{1,3}){3})", line):
            ips.add(match.group(1))
    return ips


def _suggest_free_ip(static_ip: str, allocated: set[str]) -> str | None:
    """Return the lowest free usable host IP in the requested subnet, or None.

    Skips the conventional gateway (first usable address) so a suggestion never
    collides with the router.
    """
    network = ipaddress.ip_interface(static_ip).network
    taken = {ipaddress.ip_address(ip) for ip in allocated}
    gateway_guess = network.network_address + 1
    for host in network.hosts():
        if host == gateway_guess:
            continue
        if host not in taken:
            return str(host)
    return None
