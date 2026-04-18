# pmx Provisioning — Phase 1: Repository Scaffolding and CLI Shell

**Goal:** Create the repository layout, package, Ansible scaffolding, and a functional `pmx` CLI entrypoint with all subcommand stubs, flag parsing, and the AD-credential prompt/env-cache logic in place. No provisioning yet — every subcommand prints "not yet implemented" and exits 1.

**Architecture:** Python CLI (Click 8.3) installed as the entrypoint `pmx = pmx.cli:main` via `pyproject.toml`. Ansible scaffolding (`ansible/ansible.cfg`, `ansible/inventory/proxmox.yml`, `ansible/group_vars/proxmox.yml`, empty `ansible/playbooks/provision.yml`) sits alongside. Workstation config loaded from `~/.config/pmx/config.yml`. Credential handling isolated in `pmx/credentials.py` so it can be unit-tested later.

**Tech Stack:** Python 3.12, Click 8.3.x, ansible-core 2.17.x, proxmoxer 2.3.x, uv for dependency management.

**Scope:** Phase 1 of 8.

**Codebase verified:** 2026-04-18. Greenfield — none of the design-assumed paths exist. `pmx/`, `ansible/`, `ansible/playbooks/`, `ansible/inventory/`, `ansible/group_vars/`, `state/`, `tests/` all need creation. Git is clean on `main` at commit `3d15f8c`. `/etc/ceph/ceph.conf` and `/etc/ceph/cephfs.secret` are present on this workstation (mode 0644). Passwordless `ssh root@192.168.9.12` confirmed working.

**External dependency investigation findings:**
- ✓ Python 3.12 is the conservative LTS pick (supported through Oct 2028). Python 3.13 exists but adds little for a CLI.
- ✓ Click 8.3.2 is current stable; 8.2.2 was yanked for boolean-option regression — avoid.
- ✓ ansible-core 2.17.x or 2.18.x is current; 2.20.4 is latest but 2.17/2.18 are the conservative targets.
- ✓ proxmoxer 2.3.0 (March 2026) is actively maintained.
- ✓ `uv` is the 2026 consensus for Python project management (10–100× faster than pip). Use `uv` with `pyproject.toml` + `uv.lock`.
- 📖 Sources: [Click PyPI](https://pypi.org/project/click/), [ansible-core releases](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html), [proxmoxer 2.3.0](https://pypi.org/project/proxmoxer/), [uv docs](https://docs.astral.sh/uv/).

---

## Acceptance Criteria Coverage

This phase is infrastructure — no behavioral ACs are implemented. Verification is operational (install succeeds, CLI runs, `--help` prints subcommands, credential prompt fires).

**Verifies: None** (infrastructure phase).

Behavioral ACs begin in Phase 3 (VM creation) and Phase 4 (LXC creation).

---

<!-- START_TASK_1 -->
### Task 1: Project scaffolding (pyproject.toml, uv lock, package layout)

**Files:**
- Create: `/home/sysop/proxmox-manage/pyproject.toml`
- Create: `/home/sysop/proxmox-manage/pmx/__init__.py` (empty, or with `__version__ = "0.1.0"`)
- Create: `/home/sysop/proxmox-manage/.python-version` (contents: `3.12`)
- Create: `/home/sysop/proxmox-manage/.gitignore`

**Implementation:**

`pyproject.toml` configures the project with uv, declares runtime deps (Click, ansible-core, proxmoxer, PyYAML), dev deps (pytest, ruff), and the `pmx` entrypoint:

```toml
[project]
name = "pmx"
version = "0.1.0"
description = "Proxmox provisioning CLI"
requires-python = ">=3.12"
dependencies = [
    "click>=8.3,<9",
    "ansible-core>=2.17,<2.19",
    "proxmoxer>=2.3,<3",
    "requests>=2.31",
    "pyyaml>=6.0",
]

[project.scripts]
pmx = "pmx.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["pmx"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

`.gitignore`:
```
__pycache__/
*.py[cod]
.venv/
.ruff_cache/
.pytest_cache/
dist/
build/
*.egg-info/
.python-version
uv.lock
state/guests.jsonl
```

Note on `uv.lock`: we intentionally do NOT check in `uv.lock` for this personal tool — every install resolves fresh against `pyproject.toml` constraints. If this becomes a team tool later, check it in.

`pmx/__init__.py`:
```python
__version__ = "0.1.0"
```

**Step 1: Create files**

Write the three files above.

**Step 2: Verify operationally**

```bash
cd /home/sysop/proxmox-manage
uv sync
```
Expected: resolves and installs dependencies into `.venv/`, creates `uv.lock` (uncommitted).

```bash
uv run python -c "import pmx; print(pmx.__version__)"
```
Expected output: `0.1.0`

```bash
uv run pmx --help 2>&1 || true
```
Expected: `ModuleNotFoundError: No module named 'pmx.cli'` (cli.py doesn't exist yet — that's Task 2). This is the expected failure mode; Task 7 will verify it works end-to-end.

**Step 3: Commit**

```bash
git add pyproject.toml pmx/__init__.py .gitignore
git commit -m "$(cat <<'EOF'
chore: scaffold pmx python package with uv

Initializes the package with Click/ansible-core/proxmoxer deps
and a `pmx` entrypoint pointing at pmx.cli:main (created in Task 2).
EOF
)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: CLI entrypoint with subcommand stubs

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/cli.py`

**Implementation:**

`pmx/cli.py` uses Click groups + subcommands. Each subcommand is a stub that prints a message and exits 1 (so scripts don't silently succeed). Flag surface for `pmx new` includes every flag the design document specifies — even if we don't wire them up until later phases, argparse errors early are better than surprises.

```python
"""pmx — Proxmox provisioning CLI.

Subcommands:
  new          create a VM or LXC and configure it end-to-end
  destroy      remove a guest (AD computer object + Proxmox resource)
  reconfigure  re-run the configure phase against an existing guest
  verify       smoke-test a guest (id lookup, sudo, sssd)
  seed         download and build base VM + LXC templates
"""

from __future__ import annotations

import sys

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
@click.option("--no-domain", is_flag=True, help="Skip AD domain join.")
def cmd_new(**kwargs: object) -> None:
    """Create a new guest."""
    from pmx.credentials import ensure_ad_password

    if not kwargs["no_domain"]:
        ensure_ad_password()
    click.echo(f"pmx new not yet implemented (args={kwargs})", err=True)
    sys.exit(NOT_IMPLEMENTED_EXIT)


@main.command("destroy")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip interactive confirmation.")
def cmd_destroy(name: str, yes: bool) -> None:
    """Destroy a guest (removes AD computer object and Proxmox resource)."""
    click.echo(f"pmx destroy not yet implemented (name={name}, yes={yes})", err=True)
    sys.exit(NOT_IMPLEMENTED_EXIT)


@main.command("reconfigure")
@click.argument("name")
def cmd_reconfigure(name: str) -> None:
    """Re-run the configure phase against an existing guest."""
    click.echo(f"pmx reconfigure not yet implemented (name={name})", err=True)
    sys.exit(NOT_IMPLEMENTED_EXIT)


@main.command("verify")
@click.argument("name")
def cmd_verify(name: str) -> None:
    """Run smoke tests against a domain-joined guest."""
    click.echo(f"pmx verify not yet implemented (name={name})", err=True)
    sys.exit(NOT_IMPLEMENTED_EXIT)


@main.command("seed")
def cmd_seed() -> None:
    """Download and build base VM + LXC templates on the cluster."""
    click.echo("pmx seed not yet implemented", err=True)
    sys.exit(NOT_IMPLEMENTED_EXIT)


if __name__ == "__main__":
    main()
```

**Step 1: Create file**

Write `pmx/cli.py` with the content above.

**Step 2: Verify operationally**

```bash
cd /home/sysop/proxmox-manage
uv run pmx --help
```
Expected: Help text listing all five subcommands (`new`, `destroy`, `reconfigure`, `verify`, `seed`).

```bash
uv run pmx new --help
```
Expected: Help text showing every flag (`--name`, `--kind`, `--os`, `--cores`, `--memory`, `--disk`, `--cephfs`, `--rbd-disk`, `--extra-packages`, `--static-ip`, `--no-domain`).

```bash
uv run pmx seed; echo "exit=$?"
```
Expected: `pmx seed not yet implemented` on stderr, `exit=1`.

**Step 3: Commit**

```bash
git add pmx/cli.py
git commit -m "feat(cli): add pmx CLI entrypoint with subcommand stubs

All flag surfaces from the design are wired up now so early argparse
errors surface before real provisioning lands in subsequent phases.
Stubs exit 1 so scripts that invoke the CLI pre-implementation fail loud."
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: AD credential handling (prompt + env cache)

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/credentials.py`

**Implementation:**

Separate module so it stays unit-testable. Behavior: if `AD_JOIN_PASSWORD` is already set in the environment, reuse it silently. Otherwise prompt via `getpass.getpass` (hidden input), export into `os.environ` so subsequent invocations in the same Python process see it, and return the value. On empty input, raise `click.Abort()` — we never cache an empty string. A one-liner hint is printed the first time so the user knows how to rehydrate into new shells.

```python
"""AD credential handling for pmx.

The AD join password is prompted once per shell session, cached in
`$AD_JOIN_PASSWORD`, and reused by subsequent pmx invocations. On a
fresh shell the user is prompted (hidden input); a hint is printed
showing how to export the password for future shells if desired.
"""

from __future__ import annotations

import getpass
import os

import click

ENV_VAR = "AD_JOIN_PASSWORD"


def ensure_ad_password() -> str:
    """Return the AD join password, prompting if not already cached.

    The returned value is also exported into os.environ[ENV_VAR] so
    downstream subprocess calls (ansible-playbook) inherit it.
    """
    cached = os.environ.get(ENV_VAR)
    if cached:
        return cached

    password = getpass.getpass(prompt="AD join password (jtd@broken.wrx): ")
    if not password:
        click.echo("No password entered; aborting.", err=True)
        raise click.Abort()

    os.environ[ENV_VAR] = password
    click.echo(
        f"Cached credential for this process. "
        f"To reuse across shells: export {ENV_VAR}=<password>",
        err=True,
    )
    return password
```

**Step 1: Create file**

Write `pmx/credentials.py`.

**Step 2: Verify operationally**

```bash
cd /home/sysop/proxmox-manage
uv run python -c "from pmx.credentials import ensure_ad_password, ENV_VAR; print(ENV_VAR)"
```
Expected: `AD_JOIN_PASSWORD`

```bash
AD_JOIN_PASSWORD=testpw uv run python -c "from pmx.credentials import ensure_ad_password; print(ensure_ad_password())"
```
Expected: `testpw` (no prompt — env var already set).

**Interactive sanity check (optional):**
```bash
env -u AD_JOIN_PASSWORD uv run pmx new --name z --kind vm --os ubuntu
```
Expected: Prompts "AD join password (jtd@broken.wrx): " with hidden input, then (after any input) prints the "not yet implemented" stub message and exits 1.

**Step 3: Commit**

```bash
git add pmx/credentials.py
git commit -m "feat(cli): add AD credential prompt with per-process env cache

Prompt is via getpass (hidden); value is exported into os.environ so
ansible-playbook subprocesses inherit it. Empty input aborts rather
than caching a bogus value."
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Workstation config loader

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/config.py`
- Create: `/home/sysop/proxmox-manage/docs/config-example.yml` (reference — NOT shipped as live config)

**Implementation:**

The tool's workstation config lives at `~/.config/pmx/config.yml` and holds: Proxmox SSH alias for the node to run `qm`/`pct` on, default storage pool, default bridge, AD domain name, AD join username, and the path to the repo-local `state/guests.jsonl` (usually `state/guests.jsonl` relative to the repo root). Loading is done lazily — only when a subcommand actually needs it.

```python
"""Workstation-side configuration for pmx.

Config lives at ~/.config/pmx/config.yml. This module provides a
typed loader so subcommands can pull settings without parsing YAML
everywhere.
"""

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
```

`docs/config-example.yml`:
```yaml
# Example config for pmx. Copy to ~/.config/pmx/config.yml and edit.
proxmox_ssh_host: root@192.168.9.12
proxmox_api_host: 192.168.9.12
default_node: pve01
default_storage: bwrx
default_lxc_storage: cephfs
default_bridge: vmbr0
ad_domain: broken.wrx
ad_realm: BROKEN.WRX
ad_join_user: jtd
ceph_conf_path: /etc/ceph/ceph.conf
ceph_secret_path: /etc/ceph/cephfs.secret
ceph_mons:
  - 192.168.9.11
  - 192.168.9.12
  - 192.168.9.13
  - 192.168.9.14
state_log_path: state/guests.jsonl
```

**Step 1: Create files**

Write `pmx/config.py` and `docs/config-example.yml`.

**Step 2: Verify operationally**

```bash
cd /home/sysop/proxmox-manage
uv run python -c "from pmx.config import Config, CONFIG_PATH; print(CONFIG_PATH)"
```
Expected: `/home/sysop/.config/pmx/config.yml` (path doesn't need to exist yet).

```bash
mkdir -p ~/.config/pmx && cp docs/config-example.yml ~/.config/pmx/config.yml
uv run python -c "from pmx.config import load; c = load(); print(c.ad_domain, c.default_storage)"
```
Expected: `broken.wrx bwrx`

**Step 3: Commit**

```bash
git add pmx/config.py docs/config-example.yml
git commit -m "feat(cli): add workstation config loader

~/.config/pmx/config.yml holds SSH target, default pools/bridges,
AD realm/domain, Ceph config paths. docs/config-example.yml is the
copy-me-and-edit template."
```
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Ansible scaffolding (ansible.cfg, inventory, group_vars, empty provision.yml)

**Files:**
- Create: `/home/sysop/proxmox-manage/ansible/ansible.cfg`
- Create: `/home/sysop/proxmox-manage/ansible/inventory/proxmox.yml`
- Create: `/home/sysop/proxmox-manage/ansible/group_vars/proxmox.yml`
- Create: `/home/sysop/proxmox-manage/ansible/group_vars/all.yml`
- Create: `/home/sysop/proxmox-manage/ansible/playbooks/provision.yml`
- Create: `/home/sysop/proxmox-manage/ansible/requirements.yml`

**Implementation:**

`ansible/ansible.cfg`:
```ini
[defaults]
inventory = inventory/proxmox.yml
roles_path = roles
collections_path = .ansible/collections
host_key_checking = False
stdout_callback = yaml
bin_ansible_callbacks = True
retry_files_enabled = False
forks = 5

[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o StrictHostKeyChecking=accept-new
```

`ansible/inventory/proxmox.yml`:
```yaml
# Static inventory of Proxmox cluster nodes.
# Guests are added dynamically at provision time via `ansible.builtin.add_host`.
all:
  children:
    proxmox:
      hosts:
        pve01:
          ansible_host: 192.168.9.12
          ansible_user: root
      # Add further cluster nodes here as pve02, pve03 with their ansible_host.
```

`ansible/group_vars/proxmox.yml`:
```yaml
# Variables for the `proxmox` group (the hosts running pct/qm).
ansible_python_interpreter: /usr/bin/python3
```

`ansible/group_vars/all.yml`:
```yaml
# Defaults shared across all plays. Override per-run with -e extra vars.
ad_domain: broken.wrx
ad_realm: BROKEN.WRX
ad_join_user: jtd

default_storage: bwrx
default_lxc_storage: cephfs
default_bridge: vmbr0

# Paths on the workstation (filled in by the CLI from ~/.config/pmx/config.yml)
ceph_conf_path: /etc/ceph/ceph.conf
ceph_secret_path: /etc/ceph/cephfs.secret
ceph_mons:
  - 192.168.9.11
  - 192.168.9.12
  - 192.168.9.13
  - 192.168.9.14
```

`ansible/requirements.yml`:
```yaml
collections:
  - name: community.proxmox
    version: ">=1.6.0,<2.0.0"
  - name: ansible.posix
    version: ">=1.5.4"
  - name: community.general
    version: ">=9.0.0"
```

`ansible/playbooks/provision.yml` (skeleton — Phase 3 will fill the create play, Phase 5 the configure play):
```yaml
---
# Top-level provisioning playbook.
# Invoked by pmx CLI with extra-vars: guest_name, guest_kind (vm|lxc),
# guest_os (ubuntu|rocky), cores, memory, disk, cephfs_mounts (list),
# rbd_disk (int|null), extra_packages (list), static_ip (str|null),
# domain_join (bool). See ansible/group_vars/all.yml for defaults.

- name: Create guest on Proxmox
  hosts: proxmox
  gather_facts: false
  # Phase 3 (VM) and Phase 4 (LXC) populate this play with create_vm / create_lxc roles.
  tasks: []

- name: Configure guest
  hosts: just_created
  gather_facts: true
  # Phase 5 wires in common + ad_join roles; Phase 6 wires in optional add-ons.
  tasks: []
```

**Step 1: Create files**

Write all six files above.

**Step 2: Verify operationally**

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-galaxy collection install -r requirements.yml -p .ansible/collections
```
Expected: `community.proxmox`, `ansible.posix`, and `community.general` install to `.ansible/collections/ansible_collections/`.

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-inventory --list
```
Expected: JSON output showing the `proxmox` group with `pve01` mapped to `192.168.9.12`.

```bash
cd /home/sysop/proxmox-manage/ansible
uv run ansible-playbook --syntax-check playbooks/provision.yml
```
Expected: `playbook: playbooks/provision.yml` — no syntax errors.

**Step 3: Commit**

`.ansible/collections/` is gitignored (it's a local install).

Append to `.gitignore`:
```
ansible/.ansible/
```

```bash
cd /home/sysop/proxmox-manage
git add ansible/ .gitignore
git commit -m "chore(ansible): scaffold inventory, group_vars, and playbook skeleton

Static inventory with pve01 mapped to 192.168.9.12; group_vars hold
AD realm/domain defaults and default storage/bridge. provision.yml
has two empty plays (create on proxmox, configure on just_created)
that later phases populate."
```
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Wire CLI to invoke ansible-playbook (shell-out scaffold, still prints "not implemented")

**Files:**
- Create: `/home/sysop/proxmox-manage/pmx/ansible_runner.py`

**Implementation:**

A tiny wrapper module that builds an `ansible-playbook` command with `-e` extra-vars from a dict and `subprocess.run`s it inheriting the current env (so `$AD_JOIN_PASSWORD` flows through). Stubs are kept honest: `cmd_new` still prints "not yet implemented" and exits — but now it will also *optionally* print the constructed command with `--dry-run`, which helps Phase 3/4 debugging later without changing the public surface now.

```python
"""Invoke ansible-playbook from pmx."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import click


REPO_ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO_ROOT / "ansible"


def run_playbook(playbook: str, extra_vars: dict[str, object], dry_run: bool = False) -> int:
    """Run ansible-playbook with the given extra-vars. Returns the exit code.

    `playbook` is a path relative to ansible/playbooks/ (e.g. 'provision.yml').
    """
    playbook_path = ANSIBLE_DIR / "playbooks" / playbook
    if not playbook_path.exists():
        click.echo(f"playbook not found: {playbook_path}", err=True)
        return 2

    cmd = [
        "ansible-playbook",
        str(playbook_path),
        "-e",
        json.dumps(extra_vars),
    ]
    if dry_run:
        click.echo("+ " + " ".join(cmd), err=True)
        return 0

    result = subprocess.run(cmd, cwd=str(ANSIBLE_DIR), env=os.environ.copy(), check=False)
    return result.returncode
```

Edit `pmx/cli.py` `cmd_new` to add a `--dry-run` hidden flag that prints the would-be ansible-playbook command instead of failing with "not implemented":

Modify `pmx/cli.py:cmd_new` — replace the existing body:

```python
@click.option("--dry-run", is_flag=True, hidden=True, help="Print the ansible command that would run.")
def cmd_new(**kwargs: object) -> None:
    """Create a new guest."""
    from pmx.credentials import ensure_ad_password
    from pmx.ansible_runner import run_playbook

    if not kwargs["no_domain"]:
        ensure_ad_password()

    if kwargs["dry_run"]:
        rc = run_playbook("provision.yml", _extra_vars_from(kwargs), dry_run=True)
        sys.exit(rc)

    click.echo(f"pmx new not yet implemented (args={kwargs})", err=True)
    sys.exit(NOT_IMPLEMENTED_EXIT)


def _extra_vars_from(kwargs: dict[str, object]) -> dict[str, object]:
    """Translate click kwargs into the ansible extra-vars contract."""
    return {
        "guest_name": kwargs["name"],
        "guest_kind": kwargs["kind"],
        "guest_os": kwargs["os_family"],
        "cores": kwargs["cores"],
        "memory": kwargs["memory"],
        "disk": kwargs["disk"],
        "cephfs_mounts": [c for c in kwargs["cephfs"]] if kwargs["cephfs"] else [],
        "rbd_disk": kwargs["rbd_disk"],
        "extra_packages": [p for p in (kwargs["extra_packages"] or "").split(",") if p],
        "static_ip": kwargs["static_ip"],
        "domain_join": not kwargs["no_domain"],
    }
```

**Step 1: Create/modify files**

Create `pmx/ansible_runner.py` and modify `pmx/cli.py:cmd_new` as shown.

**Step 2: Verify operationally**

```bash
cd /home/sysop/proxmox-manage
AD_JOIN_PASSWORD=test uv run pmx new --name foo --kind vm --os ubuntu --dry-run
```
Expected: prints something like:
```
+ ansible-playbook /home/sysop/proxmox-manage/ansible/playbooks/provision.yml -e {"guest_name": "foo", ...}
```
Exit 0.

```bash
cd /home/sysop/proxmox-manage
AD_JOIN_PASSWORD=test uv run pmx new --name foo --kind vm --os ubuntu
```
Expected: "pmx new not yet implemented" on stderr, exit 1.

**Step 3: Commit**

```bash
git add pmx/ansible_runner.py pmx/cli.py
git commit -m "feat(cli): wire CLI to ansible-playbook (hidden --dry-run prints command)

The runner builds extra-vars JSON and shells out to ansible-playbook
with os.environ inherited so \$AD_JOIN_PASSWORD flows through. --dry-run
is hidden and intended for debugging later phases."
```
<!-- END_TASK_6 -->

<!-- START_TASK_7 -->
### Task 7: Install check and sanity suite

**Files:**
- Create: `/home/sysop/proxmox-manage/README.md`

**Implementation:**

A minimal README with install and "what works today" notes, so anyone (including future-you) landing in this repo can get bootstrapped in under two minutes.

```markdown
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
```

**Step 1: Create file**

Write `README.md`.

**Step 2: Verify operationally**

Full end-to-end sanity check:

```bash
cd /home/sysop/proxmox-manage
uv sync
uv run pmx --help
```
Expected: Five subcommands listed.

```bash
uv run pmx new --help
```
Expected: All 12 flags listed (including hidden `--dry-run` only if `--help` doesn't hide it — which it does; that's fine).

```bash
env -u AD_JOIN_PASSWORD uv run pmx new --name dummy --kind vm --os ubuntu
```
Expected: Prompts for password (hidden), any input, then prints stub message + exits 1.

```bash
AD_JOIN_PASSWORD=x uv run pmx destroy some-name
```
Expected: "pmx destroy not yet implemented (name=some-name, yes=False)" on stderr, exit 1.

```bash
cd /home/sysop/proxmox-manage/ansible && uv run ansible-playbook --syntax-check playbooks/provision.yml
```
Expected: No syntax errors.

**Step 3: Commit**

```bash
cd /home/sysop/proxmox-manage
git add README.md
git commit -m "docs: add README with install and status notes"
```
<!-- END_TASK_7 -->

---

## Phase 1 done when

- `uv sync` succeeds in the repo
- `uv run pmx --help` lists all five subcommands
- `uv run pmx new --help` shows every flag described in the design
- `env -u AD_JOIN_PASSWORD uv run pmx new --name foo --kind vm --os ubuntu` prompts for password then exits 1 with the stub message
- `AD_JOIN_PASSWORD=... uv run pmx new ... --dry-run` prints the constructed ansible-playbook command
- `uv run ansible-galaxy collection install -r ansible/requirements.yml` installs `community.proxmox`
- `uv run ansible-playbook --syntax-check ansible/playbooks/provision.yml` passes
- Clean `git status` after all seven commits

No functional acceptance criteria verified in this phase. Behavioral ACs start at Phase 3.
