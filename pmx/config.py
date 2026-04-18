"""Workstation-side configuration for pmx.

Config lives at ~/.config/pmx/config.yml. This module provides a
typed loader so subcommands can pull settings without parsing YAML
everywhere.
"""

# FCIS: functional core

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import click
import yaml


CONFIG_PATH = Path(os.path.expanduser("~/.config/pmx/config.yml"))


@dataclass(frozen=True)
class Config:
    proxmox_ssh_host: str         # e.g. "root@192.168.9.12"
    proxmox_api_host: str         # e.g. "192.168.9.12" (sans user)
    default_node: str             # e.g. "pve01" (the node qm/pct runs on)
    default_storage: str          # e.g. "bwrx"      (RBD pool for VM disks)
    default_lxc_storage: str      # e.g. "cephfs"    (for LXC rootfs / templates)
    default_bridge: str           # e.g. "vmbr0"
    ad_domain: str                # e.g. "broken.wrx"
    ad_realm: str                 # e.g. "BROKEN.WRX"
    ad_join_user: str             # e.g. "jtd"
    ceph_conf_path: str           # e.g. "/etc/ceph/ceph.conf"
    ceph_secret_path: str         # e.g. "/etc/ceph/cephfs.secret"
    ceph_mons: list[str]          # e.g. ["192.168.9.11","192.168.9.12","192.168.9.13","192.168.9.14"]
    state_log_path: str           # e.g. "state/guests.jsonl" (relative to repo root)


def load() -> Config:
    if not CONFIG_PATH.exists():
        click.echo(
            f"pmx config not found at {CONFIG_PATH}. "
            f"See docs/config-example.yml for a template.",
            err=True,
        )
        raise click.Abort()
    raw = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    try:
        return Config(**raw)
    except TypeError as exc:
        click.echo(f"pmx config at {CONFIG_PATH} is malformed: {exc}", err=True)
        raise click.Abort() from exc
