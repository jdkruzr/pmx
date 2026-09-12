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

# Keys that older configs carried and that no longer mean anything. The
# workstation used to be a Ceph client whose admin secret was copied into every
# guest; guests now get their own CephX identity minted on the node. Refuse to
# load rather than silently ignore, so nobody keeps believing the file matters.
_REMOVED_KEYS = frozenset({"ceph_conf_path", "ceph_secret_path"})


@dataclass(frozen=True)
class Config:
    proxmox_ssh_host: str  # e.g. "root@192.168.9.12"
    proxmox_api_host: str  # e.g. "192.168.9.12" (sans user)
    default_node: str  # e.g. "pve01" (the node qm/pct runs on)
    default_storage: str  # e.g. "bwrx"      (RBD pool for VM disks)
    default_lxc_storage: str  # e.g. "cephfs"    (for LXC rootfs / templates)
    default_bridge: str  # e.g. "vmbr0"
    ad_domain: str  # e.g. "broken.wrx"
    ad_realm: str  # e.g. "BROKEN.WRX"
    ad_join_user: str  # e.g. "jtd"
    ceph_mons: list[str]  # e.g. ["192.168.9.11","192.168.9.12","192.168.9.13","192.168.9.14"]
    state_log_path: str  # e.g. "state/guests.jsonl" (relative to repo root)
    # ssh target for the Samba AD DC, where `pmx destroy` runs DNS/computer-object
    # deregistration with the DC's own tooling. Empty disables that step. Defaulted
    # so existing configs keep loading; set it to enable DC-side teardown.
    dc_ssh_host: str = ""  # e.g. "sysop@192.168.9.20"
    # CephX key type for the per-guest `client.<name>` identities pmx mints.
    # Guest kernels up to 6.8 only speak `aes`; flip to `aes256k` once every
    # CephFS-mounting guest runs a kernel that supports it (7.0+).
    cephx_key_type: str = "aes"


def load() -> Config:
    if not CONFIG_PATH.exists():
        click.echo(
            f"pmx config not found at {CONFIG_PATH}. See docs/config-example.yml for a template.",
            err=True,
        )
        raise click.Abort()
    raw = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    stale = sorted(_REMOVED_KEYS & set(raw))
    if stale:
        click.echo(
            f"pmx config at {CONFIG_PATH} has obsolete keys {stale}: the workstation is "
            f"no longer a Ceph client; guests get per-guest CephX keys minted on the "
            f"node. Delete those keys and re-run.",
            err=True,
        )
        raise click.Abort()
    try:
        return Config(**raw)
    except TypeError as exc:
        click.echo(f"pmx config at {CONFIG_PATH} is malformed: {exc}", err=True)
        raise click.Abort() from exc
