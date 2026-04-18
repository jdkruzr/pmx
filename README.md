# pmx — Proxmox Provisioning CLI

Automated creation of Proxmox VMs and LXC containers with automatic
Active Directory domain join. Runs on your workstation, shells out to
Ansible to drive the cluster.

## Install

```bash
cd /home/sysop/proxmox-manage
uv sync
uv run pmx --help
```

## First-time config

```bash
mkdir -p ~/.config/pmx
cp docs/config-example.yml ~/.config/pmx/config.yml
# edit ~/.config/pmx/config.yml to match your environment
```

## Status

This is early-phase scaffolding. Subcommands (`new`, `destroy`,
`reconfigure`, `verify`, `seed`) all exit with "not yet implemented"
until their respective implementation phases land.

## Docs

- Design: `docs/design-plans/2026-04-17-pmx-provisioning.md`
- Implementation plans: `docs/implementation-plans/2026-04-18-pmx-provisioning/`
