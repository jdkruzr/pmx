# Ansible Layer

Last verified: 2026-04-18

## Purpose

Everything that runs against the Proxmox cluster or inside guests. Invoked
exclusively via `pmx` (Python CLI shelling out to `ansible-playbook`). Roles
are single-purpose and composable; playbooks are thin orchestrators.

## Contracts

- **Exposes:** Five playbooks runnable via `run_playbook()` from `pmx/`:
  - `provision.yml` — create + configure (new guests)
  - `_configure.yml` — configure only (imported by provision, reused by reconfigure)
  - `destroy.yml` — AD cleanup + `qm/pct destroy --purge`
  - `reconfigure.yml` — re-run `_configure.yml` against an existing guest
  - `seed.yml` — build base templates on the cluster
- **Guarantees:**
  - Every playbook targets either `{{ target_node }}` (cluster node) or
    `just_created` (the guest, added dynamically via `add_host`).
  - `provision.yml` leaves the guest in group `just_created` with
    `ansible_host` = the guest's IP so `_configure.yml` can reach it.
  - Playbooks are idempotent where possible; create roles detect half-built
    state (e.g. VM exists but cloud-init not complete) and resume.
  - `post_create_hook` role runs last in `_configure.yml` and NEVER mutates
    the guest — it writes to the workstation state log and makes calls to
    external systems only. See `docs/extending-post-create.md`.
- **Expects:** Extra-vars from `pmx.translate.extra_vars_from()` plus
  cluster/AD config (`target_node`, `default_storage`, `default_lxc_storage`,
  `default_bridge`, `ad_domain`, `ad_realm`, `ad_join_user`,
  `proxmox_api_host`, `state_log_path`). Full list in `provision.yml` header
  and `docs/extending-post-create.md`.

## Dependencies

- **Uses:**
  - Collections pinned in `requirements.yml` (includes `ansible.utils` for
    `ipaddr`/`ipmath`).
  - Custom filter `pmx_parse_cephfs` from `filter_plugins/pmx_filters.py`.
  - SSH access to Proxmox nodes (key auth) and to guests (cloud-init injected
    key for VMs; root password or key for LXC).
- **Used by:** `pmx/ansible_runner.py` only.
- **Boundary:** Roles must not assume workstation filesystem layout. The CLI
  passes `state_log_path` as an absolute path. Don't hard-code `~/`.

## Role Map

| Role | When | Target | Summary |
|---|---|---|---|
| `create_vm` | `new --kind vm` | Proxmox node | Clone template, set cloud-init, start, capture MAC+IP, `add_host` to `just_created` |
| `create_lxc` | `new --kind lxc` | Proxmox node | `pct create` from template, configure subuid/subgid, start, `add_host` |
| `seed_ubuntu_vm` / `seed_rocky_vm` / `seed_rocky_lxc` | `seed` | Proxmox node | Download image, build base template |
| `common` | every configure | guest | `apt`/`dnf` bootstrap; includes `ubuntu.yml` or `rocky.yml` |
| `ad_join_common` | via `ad_join_*` | guest | Shared sssd.conf + sudoers drop-in templates |
| `ad_join_ubuntu` / `ad_join_rocky` | `domain_join=true` | guest | `realm join` with OS-specific package set |
| `mount_cephfs` | `cephfs_mounts` non-empty | guest | VM path: kernel mount via `/etc/fstab`; LXC path: bind-mount from host |
| `attach_rbd_disk` | `rbd_disk` non-null, VM only | Proxmox node | `qm set` an additional RBD volume |
| `extra_packages` | `extra_packages` non-empty | guest | Install operator-supplied package list |
| `post_create_hook` | always last | guest | Append to `state/guests.jsonl`; extension point |

## Key Decisions

- **Proxmox node as ansible host, not API:** Uses `qm`/`pct` CLI over SSH to
  `{{ target_node }}`. Avoids proxmoxer/API auth complexity and matches how
  operators debug by hand.
- **Two-play provision:** Play 1 (cluster node) creates the guest and
  `add_host`s it; Play 2 (`_configure.yml`, group `just_created`) configures
  it. This lets `reconfigure.yml` reuse Play 2 verbatim.
- **`ad_join_common` as a shared role, not duplicated templates:** sssd.conf
  and sudoers drop-in are identical across Ubuntu/Rocky; the OS-specific
  `ad_join_*` roles handle package management + realm join invocation and
  then include `ad_join_common/apply.yml` for config.
- **LXC CephFS via bind-mount:** Unprivileged LXCs can't run the kernel
  CephFS client; the host mounts CephFS and bind-mounts the subtree into
  the container.
- **Half-built detection (AC6.3):** `create_vm` and `create_lxc` check
  whether the VMID already exists and skip creation if so, letting the
  configure play retry against an existing guest.
- **`LC_ALL=C` on `realm join`:** realmd parses its own stderr; locale
  differences break the parse.

## Invariants

- `just_created` always has exactly one host after Play 1 of `provision.yml`.
- `guest_mac` in post-create extra-vars matches the NIC bound to `guest_ip`
  (selected explicitly, not "first MAC found").
- `pmx_parse_cephfs` rejects empty destinations and prepends `/` to subpath
  if missing.
- `post_create_hook` runs last, unconditionally — even when individual
  prior tasks were skipped.
- LXC create uses `pveam`'s short template name (e.g. `rockylinux-9-…tar.xz`),
  never a double-`vztmpl/` prefixed path.

## Gotchas

- `ansible_become: true` in `_configure.yml` is gated on `guest_kind == 'vm'`.
  LXCs run as root already and `become: true` breaks some tasks. For LXC
  the `common` role includes only the tasks that work as root (no
  qemu-guest-agent, no `become` inside role tasks).
- `add_host` for LXC must set `ansible_become: false` explicitly or it
  inherits the configure play's default and fails.
- `destroy.yml`'s adcli cleanup uses `failed_when: false` — a missing AD
  computer object is not fatal.
- Seed playbook uses `pveam available | grep` substring match for Rocky
  LXC templates because exact names drift across Proxmox minor versions.

## Key Files

- `playbooks/provision.yml` — extra-vars header documents the contract
- `playbooks/_configure.yml` — configure-phase task order
- `group_vars/all.yml` — shared defaults
- `filter_plugins/pmx_filters.py` — `pmx_parse_cephfs` filter
- `requirements.yml` — collection pins (must include `ansible.utils`)
