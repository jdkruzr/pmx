"""Invoke ansible-playbook from pmx."""

# FCIS: imperative shell

from __future__ import annotations

import json
import os
import shlex
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
        click.echo("+ " + shlex.join(cmd), err=True)
        return 0

    result = subprocess.run(cmd, cwd=str(ANSIBLE_DIR), env=os.environ.copy(), check=False)
    return result.returncode
