"""Translate CLI arguments to Ansible extra-vars format."""

# FCIS: functional core

from __future__ import annotations


def extra_vars_from(kwargs: dict[str, object]) -> dict[str, object]:
    """Translate click kwargs into the ansible extra-vars contract."""
    return {
        "guest_name": kwargs["name"],
        "guest_kind": kwargs["kind"],
        "guest_os": kwargs["os_family"],
        "cores": kwargs["cores"],
        "memory": kwargs["memory"],
        "disk": kwargs["disk"],
        "cephfs_mounts": list(kwargs["cephfs"]) if kwargs["cephfs"] else [],
        "rbd_disk": kwargs["rbd_disk"],
        "extra_packages": [p for p in (kwargs["extra_packages"] or "").split(",") if p],
        "static_ip": kwargs["static_ip"],
        "static_gw": kwargs["static_gw"],
        "domain_join": not kwargs["no_domain"],
    }
