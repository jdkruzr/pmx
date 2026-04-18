# pmx Python Package

Last verified: 2026-04-18

## Purpose

Workstation-side frontend for the `pmx` CLI. Its job is to parse operator
intent, gather local context (config, credentials), perform cheap preflight
checks, and then hand off to `ansible-playbook` with a well-defined extra-vars
contract. No cluster-side state lives here.

## Contracts

- **Exposes:** `pmx.cli:main` (entry point registered in `pyproject.toml`).
  Subcommands: `new`, `destroy`, `reconfigure`, `verify`, `seed`.
- **Guarantees:**
  - Every subcommand exits with the playbook's return code (or 1/2 for
    local validation failures). Never swallows ansible exit codes.
  - `extra_vars_from()` output is the stable CLI→Ansible contract; adding a
    new key requires updating roles that consume it.
  - State records are append-only JSONL. Readers tolerate unknown extra
    fields only if those fields have `None`/empty defaults on `GuestRecord`.
  - `ensure_ad_password()` prompts at most once per process; caches into
    `os.environ["AD_JOIN_PASSWORD"]` so ansible-playbook inherits it.
- **Expects:**
  - `~/.config/pmx/config.yml` exists and matches the `Config` dataclass shape.
  - SSH keypair auth to `proxmox_ssh_host` (BatchMode=yes, no prompts).
  - For `new`/`reconfigure` with domain join: operator can supply an AD password.

## Dependencies

- **Uses:** Click (CLI), PyYAML (config), subprocess (ssh + ansible-playbook).
  `proxmoxer`/`requests` are declared but not currently imported — reserved
  for future API-based preflight.
- **Used by:** nothing. Top of the stack.
- **Boundary:** Never import `ansible.*` Python modules. Never read
  `state/guests.jsonl` directly — go through `pmx.state`.

## Module Map

| File | FCIS | Role |
|---|---|---|
| `cli.py` | shell | Click command group; delegates to verb modules |
| `config.py` | core | Frozen `Config` dataclass + `load()` from YAML |
| `credentials.py` | shell | `ensure_ad_password()` — prompt + env caching |
| `translate.py` | core | `extra_vars_from(kwargs)` — CLI kwargs → ansible JSON |
| `ansible_runner.py` | shell | `run_playbook(name, extra_vars, dry_run)` — subprocess wrapper |
| `preflight.py` | shell | `assert_name_available()` — name validation + cluster uniqueness |
| `state.py` | core | `GuestRecord` dataclass, `read_all/find_by_name/append` for JSONL |
| `destroy.py` | shell | `run(name, yes)` — cluster query + adcli cleanup + playbook |
| `reconfigure.py` | shell | `run(name)` — replay original build params from state log |
| `verify.py` | shell | `run(name)` — ssh-based sssd/id/sudoers smoke test |
| `seed.py` | shell | `run()` — template-build playbook launcher |

## Key Decisions

- **Shell out to ansible-playbook instead of using the ansible Python API:**
  Keeps pmx's deps small, isolates subprocess semantics, lets operators run
  the same playbook by hand for debugging.
- **One `-e '<json>'` blob per invocation:** Avoids a dozen `-e key=val`
  flags; structured types (lists, nulls) round-trip cleanly.
- **JSONL state log instead of a DB:** Append-only, human-readable, survives
  partial failures; readers take the *last* record for a name (most recent wins).
- **Name as primary key, not VMID:** VMIDs are assigned by the cluster and
  change if a guest is recreated; names are operator-chosen and stable.
- **`--dry-run` is hidden on `new`:** It prints the shell-escaped
  ansible-playbook invocation via `shlex.join` for debugging, not a user
  feature.

## Invariants

- `Config` is frozen — never mutated after load.
- `GuestRecord.created_at` is ISO8601 UTC; `append()` fills it if missing.
- `_parse_names()` in `preflight.py` is a best-effort heuristic over
  `qm list; pct list` output — it recognises status words
  `{running, stopped, suspended, paused, mounted}` and will need updating
  if Proxmox adds new container states.
- `translate.extra_vars_from()` keys are the single source of truth for
  what playbooks receive; renaming a key is a breaking change across roles.
- `destroy._query_cluster()` is authoritative for `(vmid, kind)` — the
  state log is advisory and may be missing (warning, not error).

## Gotchas

- `run_playbook()` resolves playbooks relative to `ansible/playbooks/`, and
  uses `cwd=ansible/` so roles in `ansible/roles/` and the custom filter
  plugin are auto-discovered. Don't call it from tests without mocking.
- `preflight.assert_name_available()` uses `BatchMode=yes`; if the operator
  has no ssh key to the Proxmox host, this aborts before any playbook runs.
- `reconfigure.run()` *requires* a state log record — there is no way to
  reconfigure a guest pmx didn't create.
- `verify.run()` assumes ssh user `ansible` for VMs and `root` for LXC
  (matching create_vm / create_lxc role conventions).
- `cephfs` click option is `multiple=True` → always a tuple; `translate`
  coerces to list for JSON.

## Key Files

- `cli.py` — read this first to see the subcommand surface
- `translate.py` — the extra-vars contract (29 lines, stable)
- `state.py` — JSONL schema
