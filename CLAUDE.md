# proxmox-manage (`pmx`)

Last verified: 2026-04-18

## Purpose

Workstation-driven CLI for provisioning Proxmox VMs and LXC containers with
automatic AD domain join, CephFS mounts, and RBD attachments. `pmx` is a thin
Click-based frontend; all cluster-side work is done by Ansible roles and
playbooks under `ansible/`.

## Tech Stack

- Language: Python 3.12+
- CLI: Click 8.3
- Orchestration: ansible-core 2.17–2.18 (shelled out, not imported)
- Package/lockfile: `uv` (pyproject.toml, uv.lock)
- Proxmox: SSH to one cluster node; `qm` / `pct` / `pveam` used directly
- Linting: ruff (line-length 100, target-version py312)
- Tests: pytest + pytest-mock (unit); bash harnesses for integration

## Commands

- `uv sync` — install deps
- `uv run pmx --help` — top-level help
- `uv run pmx {new,destroy,reconfigure,verify,seed} ...` — subcommands
- `uv run pytest tests/ tests/unit/` — unit tests (69 passing)
- `uv run ruff check .` — lint
- `tests/integration/*.sh` — live-cluster smoke tests (not run in CI)

## Project Structure

- `pmx/` — Python CLI package (entry point `pmx.cli:main`)
- `ansible/playbooks/` — `provision.yml`, `_configure.yml`, `destroy.yml`,
  `reconfigure.yml`, `seed.yml`
- `ansible/roles/` — one role per concern (create, seed, ad_join, mount, etc.)
- `ansible/inventory/proxmox.yml` — static list of cluster nodes; guests are
  `add_host`-ed dynamically into group `just_created` at provision time
- `ansible/group_vars/all.yml` — shared defaults (overridable via `-e`)
- `ansible/filter_plugins/pmx_filters.py` — custom Jinja filters (`pmx_parse_cephfs`)
- `docs/` — design + implementation plans, `config-example.yml`, extension guide
- `state/guests.jsonl` — append-only JSONL log of created guests (gitignored)
- `tests/` — unit tests at root; `tests/unit/` for post-Phase-1 modules;
  `tests/integration/` for bash smoke tests

## Conventions

- **FCIS (Functional Core / Imperative Shell):** Every `pmx/*.py` file is
  annotated with `# FCIS: functional core` or `# FCIS: imperative shell`.
  Pure transforms live in the core (`translate.py`, `state.py`, `config.py`);
  subprocess, network, env, and stdin/stdout live in the shell.
- **Subcommands are thin:** `pmx/cli.py` parses + validates, then delegates to
  `pmx/<verb>.py`. Avoid putting logic in `cli.py`.
- **Names are the primary key:** Guest identity is `--name`; uniqueness is
  enforced via live `qm list; pct list` check before provisioning (see
  `pmx/preflight.py`). Valid names: `^[a-zA-Z0-9][a-zA-Z0-9-]*$`.
- **Ansible is invoked, never imported:** `pmx/ansible_runner.py` shells out
  to `ansible-playbook` with a single `-e <json>` blob. Extra-vars names are
  contractual — see `pmx/translate.py`.
- **Config is centralised:** Workstation config at `~/.config/pmx/config.yml`
  (template: `docs/config-example.yml`). Loaded once per invocation via
  `pmx.config.load()` — a frozen dataclass.

## Boundaries

- Safe to edit: `pmx/`, `ansible/`, `tests/`, `docs/`
- Do not commit: `state/guests.jsonl` (runtime artefact), `~/.config/pmx/config.yml`
  (operator-local), `.venv/`, `uv.lock` changes without review
- Do not import `ansible` Python modules — we shell out to `ansible-playbook`
- Never bake AD credentials into config; `$AD_JOIN_PASSWORD` is prompted per
  shell session by `pmx.credentials.ensure_ad_password()`

## Infrastructure Access

- Proxmox host SSH: `root@192.168.9.12` (passwordless from this workstation)
- AD domain: `broken.wrx` (realm `BROKEN.WRX`), join user `jtd`
- Default storage pools: `bwrx` (RBD for VM disks), `cephfs` (LXC rootfs + templates)

## Where to Look Next

- `pmx/CLAUDE.md` — Python module contracts (CLI ↔ Ansible boundary)
- `ansible/CLAUDE.md` — Ansible layer conventions (roles, playbooks, extra-vars contract)
- `docs/extending-post-create.md` — how to add post-provision extensions
- `docs/implementation-plans/2026-04-18-pmx-provisioning/` — phase-by-phase history
