"""pmx — Proxmox provisioning CLI.

Subcommands:
  new          create a VM or LXC and configure it end-to-end
  destroy      remove a guest (AD computer object + Proxmox resource)
  reconfigure  re-run the configure phase against an existing guest
  verify       smoke-test a guest (id lookup, sudo, sssd)
  seed         download and build base VM + LXC templates
"""

# FCIS: imperative shell

from __future__ import annotations

import sys
from pathlib import Path

import click

NOT_IMPLEMENTED_EXIT = 1


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option()
def main() -> None:
    """Proxmox provisioning CLI."""


@main.command("new")
@click.option("--name", required=True, help="Guest hostname (primary key).")
@click.option(
    "--kind",
    type=click.Choice(["vm", "lxc"]),
    required=True,
    help="Create a KVM VM or an LXC container.",
)
@click.option(
    "--os",
    "os_family",
    type=click.Choice(["ubuntu", "rocky"]),
    required=True,
    help="Guest OS family (ubuntu = 24.04, rocky = 9).",
)
@click.option("--cores", type=int, default=2, show_default=True)
@click.option("--memory", type=int, default=2048, show_default=True, help="RAM in MiB.")
@click.option("--disk", type=int, default=32, show_default=True, help="Root disk in GiB.")
@click.option(
    "--cephfs",
    multiple=True,
    help="CephFS mount, format 'subpath:/guest/path'. Repeatable.",
)
@click.option("--rbd-disk", type=int, default=None, help="Extra RBD disk size in GiB (VM only).")
@click.option(
    "--extra-packages",
    default="",
    help="Comma-separated extra packages to install post-base.",
)
@click.option(
    "--static-ip",
    default=None,
    help="Static IP/CIDR (e.g. 192.168.9.80/24). Default: DHCP.",
)
@click.option(
    "--static-gw",
    default=None,
    help="Gateway IP for --static-ip (default: first usable IP in the subnet, e.g. .1 for /24).",
)
@click.option("--no-domain", is_flag=True, help="Skip AD domain join.")
@click.option("--dry-run", is_flag=True, hidden=True, help="Print the ansible command that would run.")
def cmd_new(**kwargs: object) -> None:
    """Create a new guest."""
    from pmx.config import load
    from pmx.credentials import ensure_ad_password
    from pmx.ansible_runner import run_playbook
    from pmx.preflight import assert_name_available
    from pmx.translate import extra_vars_from

    cfg = load()

    if not kwargs["no_domain"]:
        ensure_ad_password()

    if kwargs["rbd_disk"] is not None and kwargs["kind"] == "lxc":
        click.echo("--rbd-disk is VM-only; --kind lxc cannot attach raw RBD disks.", err=True)
        sys.exit(2)

    assert_name_available(cfg, kwargs["name"])  # type: ignore[arg-type]

    extra_vars = extra_vars_from(kwargs) | {
        "target_node": cfg.default_node,
        "default_storage": cfg.default_storage,
        "default_lxc_storage": cfg.default_lxc_storage,
        "default_bridge": cfg.default_bridge,
        "ad_domain": cfg.ad_domain,
        "ad_realm": cfg.ad_realm,
        "ad_join_user": cfg.ad_join_user,
        "proxmox_api_host": cfg.proxmox_api_host,
        "state_log_path": str(Path(__file__).resolve().parent.parent / cfg.state_log_path),
    }

    if kwargs["dry_run"]:
        rc = run_playbook("provision.yml", extra_vars, dry_run=True)
        sys.exit(rc)

    rc = run_playbook("provision.yml", extra_vars)
    sys.exit(rc)


@main.command("destroy")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip interactive confirmation.")
def cmd_destroy(name: str, yes: bool) -> None:
    """Destroy a guest (removes AD computer object and Proxmox resource)."""
    from pmx import destroy
    sys.exit(destroy.run(name, yes))


@main.command("reconfigure")
@click.argument("name")
def cmd_reconfigure(name: str) -> None:
    """Re-run the configure phase against an existing guest."""
    from pmx import reconfigure
    sys.exit(reconfigure.run(name))


@main.command("verify")
@click.argument("name")
def cmd_verify(name: str) -> None:
    """Run smoke tests against a domain-joined guest."""
    from pmx import verify
    sys.exit(verify.run(name))


@main.command("seed")
def cmd_seed() -> None:
    """Download and build base VM + LXC templates on the cluster."""
    from pmx import seed

    sys.exit(seed.run())


if __name__ == "__main__":
    main()
