"""pmx seed — build base VM templates and pull LXC templates on the cluster."""

# FCIS: imperative shell

from __future__ import annotations

import click

from pmx.ansible_runner import run_playbook
from pmx.config import load


def run() -> int:
    """Load config and run seed playbook with resolved cluster parameters.

    Returns the exit code from the playbook execution.
    """
    cfg = load()
    extra_vars = {
        "target_node": cfg.default_node,
        "default_storage": cfg.default_storage,
        "default_lxc_storage": cfg.default_lxc_storage,
        "default_bridge": cfg.default_bridge,
    }
    click.echo(f"Seeding templates on node {cfg.default_node}...", err=True)
    return run_playbook("seed.yml", extra_vars)
