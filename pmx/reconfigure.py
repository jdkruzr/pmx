"""pmx reconfigure — re-run the configure phase against an existing guest."""

# FCIS: imperative shell

from __future__ import annotations

import click

from pmx.ansible_runner import run_playbook
from pmx.config import load
from pmx.credentials import ensure_ad_password
from pmx.state import find_by_name


def run(name: str) -> int:
    cfg = load()
    state = find_by_name(cfg.state_log_path, name)
    if state is None:
        click.echo(
            f"No record of {name} in {cfg.state_log_path}. "
            f"pmx reconfigure needs the original build parameters from the state log.",
            err=True,
        )
        return 1

    if state.domain_joined:
        ensure_ad_password(prompt=f"AD join password ({cfg.ad_join_user}@{cfg.ad_domain}): ")

    extra_vars = {
        "target_node": cfg.default_node,
        "guest_name": state.hostname,
        "guest_vmid": state.vmid,
        "guest_kind": state.kind,
        "guest_os": state.os,
        "guest_ip": state.ip,
        "guest_mac": state.mac,
        "domain_join": state.domain_joined,
        "cephfs_mounts": state.cephfs_mounts,
        "rbd_disk": state.rbd_disk,
        "extra_packages": state.extra_packages,
        "static_ip": state.static_ip,
        "static_gw": state.static_gw,
        "ad_domain": cfg.ad_domain,
        "ad_realm": cfg.ad_realm,
        "ad_join_user": cfg.ad_join_user,
        "ceph_conf_path": cfg.ceph_conf_path,
        "ceph_secret_path": cfg.ceph_secret_path,
        "ceph_mons": cfg.ceph_mons,
        "default_storage": cfg.default_storage,
        "default_lxc_storage": cfg.default_lxc_storage,
        "default_bridge": cfg.default_bridge,
        "proxmox_api_host": cfg.proxmox_api_host,
    }
    return run_playbook("reconfigure.yml", extra_vars)
