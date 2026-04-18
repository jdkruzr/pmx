"""pmx verify — live smoke test against a domain-joined guest."""

# FCIS: imperative shell

from __future__ import annotations

import subprocess

import click

from pmx.config import load
from pmx.state import find_by_name


def run(name: str) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)
    if state is None:
        click.echo(f"No record of {name} in {cfg.state_log_path}.", err=True)
        return 2

    ssh_user = "ansible" if state.kind == "vm" else "root"
    host = f"{ssh_user}@{state.ip}"

    # Check ordering: sssd active, then id lookup. Keeps failure messages specific.
    checks = [
        ("sssd is active", "systemctl is-active sssd", "sssd not active (AC14.2)"),
        (
            f"id Administrator@{cfg.ad_domain}",
            f"id Administrator@{cfg.ad_domain}",
            "Cannot resolve Administrator@" + cfg.ad_domain + " (AC14.3)",
        ),
        (
            "sudoers drop-in validates",
            "test -f /etc/sudoers.d/domain-admins && /usr/sbin/visudo -cf /etc/sudoers.d/domain-admins",
            "sudoers drop-in missing or invalid",
        ),
    ]

    for label, remote_cmd, err_msg in checks:
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            host,
            remote_cmd,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            click.echo(f"[FAIL] {label}: {err_msg}", err=True)
            click.echo(result.stderr, err=True)
            return 1
        click.echo(f"[ OK ] {label}")

    click.echo(f"{name}: healthy.")
    return 0
